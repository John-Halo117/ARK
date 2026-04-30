package runtime

import (
	"bytes"
	"os"
	"path/filepath"
	"time"

	"github.com/John-Halo117/ARK/arkfield/action"
	"github.com/John-Halo117/ARK/arkfield/core"
	"github.com/John-Halo117/ARK/arkfield/meta"
	"github.com/John-Halo117/ARK/arkfield/policy"
	"gopkg.in/yaml.v3"
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
	Name    string         `json:"name" yaml:"name"`
	Adapter string         `json:"adapter" yaml:"adapter"`
	Payload map[string]any `json:"payload" yaml:"payload"`
}

type ActionTable struct {
	Actions []ActionMapping `json:"actions" yaml:"actions"`
}

type RouteCost struct {
	Name    string  `json:"name" yaml:"name"`
	Cost    float64 `json:"cost" yaml:"cost"`
	MaxCost float64 `json:"max_cost" yaml:"max_cost"`
}

type RoutingTable struct {
	Routes []RouteCost `json:"routes" yaml:"routes"`
}

type Tables struct {
	Policy  policy.Table `json:"policy"`
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

// Compile reads strict YAML definition files and produces static runtime tables.
func Compile(paths DefinitionPaths) (Runtime, error) {
	var policyTable policy.Table
	if err := readDefinition(paths.Policies, &policyTable); err != nil {
		return Runtime{}, err
	}
	var actionTable ActionTable
	if err := readDefinition(paths.Actions, &actionTable); err != nil {
		return Runtime{}, err
	}
	enrichPolicyParams(policyTable.Rules, actionTable)
	enrichPolicyParams(policyTable.Policies, actionTable)
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
	if err := readYAML(raw, target); err != nil {
		return core.NewFailure("DEFINITION_PARSE_FAILED", "definition file must be strict YAML", map[string]any{"path": path, "error": err.Error()}, false)
	}
	return nil
}

func (t *ActionTable) UnmarshalYAML(value *yaml.Node) error {
	var wrapped struct {
		Actions []ActionMapping `yaml:"actions"`
	}
	if err := value.Decode(&wrapped); err == nil && len(wrapped.Actions) > 0 {
		t.Actions = wrapped.Actions
		return nil
	}
	mappings := map[string]ActionMapping{}
	if err := value.Decode(&mappings); err != nil {
		return err
	}
	t.Actions = make([]ActionMapping, 0, len(mappings))
	for name, mapping := range mappings {
		mapping.Name = name
		t.Actions = append(t.Actions, mapping)
	}
	return nil
}

func (t *RoutingTable) UnmarshalYAML(value *yaml.Node) error {
	var wrapped struct {
		Routes []RouteCost `yaml:"routes"`
	}
	if err := value.Decode(&wrapped); err == nil && len(wrapped.Routes) > 0 {
		t.Routes = wrapped.Routes
		return nil
	}
	routes := map[string]RouteCost{}
	if err := value.Decode(&routes); err != nil {
		return err
	}
	t.Routes = make([]RouteCost, 0, len(routes))
	for name, route := range routes {
		route.Name = name
		if route.Cost == 0 && route.MaxCost > 0 {
			route.Cost = route.MaxCost
		}
		t.Routes = append(t.Routes, route)
	}
	return nil
}

func enrichPolicyParams(rules []policy.Rule, actions ActionTable) {
	payloads := make(map[string]map[string]any, len(actions.Actions))
	for i := 0; i < len(actions.Actions) && i < action.MaxAdapters; i++ {
		mapping := actions.Actions[i]
		if mapping.Name != "" && len(mapping.Payload) > 0 {
			payloads[mapping.Name] = mapping.Payload
		}
	}
	for i := 0; i < len(rules) && i < policy.MaxRules; i++ {
		if len(rules[i].Params) > 0 {
			continue
		}
		payload, ok := payloads[rules[i].Action]
		if !ok {
			continue
		}
		rules[i].Params = make(map[string]any, len(payload))
		for key, value := range payload {
			if len(rules[i].Params) >= core.MaxPayloadKeys {
				break
			}
			rules[i].Params[key] = value
		}
	}
}

func readYAML(raw []byte, target any) error {
	decoder := yaml.NewDecoder(bytes.NewReader(raw))
	decoder.KnownFields(true)
	return decoder.Decode(target)
}
