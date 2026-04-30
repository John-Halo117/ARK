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
	Policy  policy.Table `json:"policy" yaml:"policy"`
	Actions ActionTable  `json:"actions" yaml:"actions"`
	Routing RoutingTable `json:"routing" yaml:"routing"`
	Meta    meta.Table   `json:"meta" yaml:"meta"`
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
	enrichPolicyParams(policyTable.Rules, actionTable)
	enrichPolicyParams(policyTable.Policies, actionTable)

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
	decoder := yaml.NewDecoder(bytes.NewReader(raw))
	decoder.KnownFields(true)
	if err := decoder.Decode(target); err != nil {
		return core.NewFailure("DEFINITION_PARSE_FAILED", "definition file must be strict YAML", map[string]any{"path": path, "error": err.Error()}, false)
	}
	return nil
}

func (t *ActionTable) UnmarshalYAML(value *yaml.Node) error {
	type actionTable ActionTable
	var listed actionTable
	if err := value.Decode(&listed); err == nil && len(listed.Actions) > 0 {
		*t = ActionTable(listed)
		return nil
	}
	if value.Kind != yaml.MappingNode {
		return nil
	}
	actions := make([]ActionMapping, 0, len(value.Content)/2)
	for i := 0; i+1 < len(value.Content) && len(actions) < action.MaxAdapters; i += 2 {
		var mapping ActionMapping
		if err := value.Content[i+1].Decode(&mapping); err != nil {
			return err
		}
		mapping.Name = value.Content[i].Value
		actions = append(actions, mapping)
	}
	t.Actions = actions
	return nil
}

func (t *RoutingTable) UnmarshalYAML(value *yaml.Node) error {
	type routingTable RoutingTable
	var listed routingTable
	if err := value.Decode(&listed); err == nil && len(listed.Routes) > 0 {
		*t = RoutingTable(listed)
		return nil
	}
	if value.Kind != yaml.MappingNode {
		return nil
	}
	routes := make([]RouteCost, 0, len(value.Content)/2)
	for i := 0; i+1 < len(value.Content) && len(routes) < MaxRoutingRows; i += 2 {
		var route RouteCost
		if err := value.Content[i+1].Decode(&route); err != nil {
			return err
		}
		route.Name = value.Content[i].Value
		route.Cost = route.MaxCost
		routes = append(routes, route)
	}
	t.Routes = routes
	return nil
}

func enrichPolicyParams(rules []policy.Rule, actionTable ActionTable) {
	payloadByAction := make(map[string]map[string]any, len(actionTable.Actions))
	for i := 0; i < len(actionTable.Actions) && i < action.MaxAdapters; i++ {
		if len(actionTable.Actions[i].Payload) > 0 {
			payloadByAction[actionTable.Actions[i].Name] = actionTable.Actions[i].Payload
		}
	}
	for i := 0; i < len(rules) && i < policy.MaxRules; i++ {
		if len(rules[i].Params) == 0 {
			rules[i].Params = payloadByAction[rules[i].Action]
		}
	}
}
