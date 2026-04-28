package runtime

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/John-Halo117/ARK/arkfield/action"
	"github.com/John-Halo117/ARK/arkfield/core"
	"github.com/John-Halo117/ARK/arkfield/meta"
	"github.com/John-Halo117/ARK/arkfield/policy"
)

const (
	MaxDefinitionBytes = 1 << 20
	MaxRoutingRows     = 64
)

type DefinitionPaths struct {
	Policies string
	Actions  string
	Routing  string
	Meta     string
}

type ActionMapping struct {
	Name    string `json:"name"`
	Adapter string `json:"adapter"`
}

type ActionTable struct {
	Actions []ActionMapping `json:"actions"`
}

type RouteCost struct {
	Name string  `json:"name"`
	Cost float64 `json:"cost"`
}

type RoutingTable struct {
	Routes []RouteCost `json:"routes"`
}

type Tables struct {
	Policy policy.Table `json:"policy"`
	Actions ActionTable  `json:"actions"`
	Routing RoutingTable `json:"routing"`
	Meta    meta.Table   `json:"meta"`
}

type Runtime struct {
	Policy policy.Engine
	Action *action.Executor
	Meta   *meta.Engine
	Tables Tables
}

func DefaultDefinitionPaths(dir string) DefinitionPaths {
	return DefinitionPaths{
		Policies: filepath.Join(dir, "policies.yaml"),
		Actions:  filepath.Join(dir, "actions.yaml"),
		Routing:  filepath.Join(dir, "routing.yaml"),
		Meta:     filepath.Join(dir, "meta.yaml"),
	}
}

func Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "runtime.compiler", RuntimeCap: 100 * time.Millisecond, MemoryCapMiB: 16}
}

// Compile reads YAML definition files encoded as strict JSON-compatible YAML and produces runtime tables.
func Compile(paths DefinitionPaths) (Runtime, error) {
	var policyTable policy.Table
	if err := readDefinition(paths.Policies, &policyTable); err != nil {
		return Runtime{}, err
	}
	var actionTable ActionTable
	if err := readDefinition(paths.Actions, &actionTable); err != nil {
		return Runtime{}, err
	}
	var routingTable RoutingTable
	if err := readDefinition(paths.Routing, &routingTable); err != nil {
		return Runtime{}, err
	}
	if len(routingTable.Routes) > MaxRoutingRows {
		return Runtime{}, core.NewFailure("ROUTING_TABLE_TOO_LARGE", "routing table exceeds bounded row count", map[string]any{"max_rows": MaxRoutingRows}, false)
	}
	var metaTable meta.Table
	if err := readDefinition(paths.Meta, &metaTable); err != nil {
		return Runtime{}, err
	}

	policyEngine, err := policy.NewEngine(policyTable)
	if err != nil {
		return Runtime{}, err
	}
	adapters := make([]action.Adapter, 0, len(actionTable.Actions))
	for i := 0; i < len(actionTable.Actions) && i < action.MaxAdapters; i++ {
		mapping := actionTable.Actions[i]
		if mapping.Name == "" || mapping.Adapter == "" {
			return Runtime{}, core.NewFailure("ACTION_MAPPING_INVALID", "action mapping requires name and adapter", map[string]any{"index": i}, false)
		}
		adapters = append(adapters, action.NewMemoryAdapter(mapping.Name))
	}
	actionExecutor, err := action.NewExecutor(adapters)
	if err != nil {
		return Runtime{}, err
	}
	metaEngine, err := meta.NewEngine(metaTable)
	if err != nil {
		return Runtime{}, err
	}
	return Runtime{
		Policy: policyEngine,
		Action: &actionExecutor,
		Meta:   metaEngine,
		Tables: Tables{Policy: policyTable, Actions: actionTable, Routing: routingTable, Meta: metaTable},
	}, nil
}

func readDefinition(path string, target any) error {
	if path == "" {
		return core.NewFailure("DEFINITION_PATH_REQUIRED", "definition path is required", nil, false)
	}
	info, err := os.Stat(path)
	if err != nil {
		return core.NewFailure("DEFINITION_READ_FAILED", "definition file is not readable", map[string]any{"path": path, "error": err.Error()}, true)
	}
	if info.Size() > MaxDefinitionBytes {
		return core.NewFailure("DEFINITION_TOO_LARGE", "definition file exceeds bounded byte size", map[string]any{"path": path, "max_bytes": MaxDefinitionBytes}, false)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return core.NewFailure("DEFINITION_READ_FAILED", "definition file read failed", map[string]any{"path": path, "error": err.Error()}, true)
	}
	if err := json.Unmarshal(raw, target); err != nil {
		return core.NewFailure("DEFINITION_PARSE_FAILED", "definition file must be strict JSON-compatible YAML", map[string]any{"path": path, "error": err.Error()}, false)
	}
	return nil
}
