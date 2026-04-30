package meta

import (
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

const (
	MaxRules       = 64
	MaxDeltaDefs   = 8
	MaxAppliedDefs = 128
)

type Rule struct {
	ID       string         `json:"id" yaml:"id"`
	When     string         `json:"when" yaml:"when"`
	If       string         `json:"if" yaml:"if"`
	Patch    map[string]any `json:"patch" yaml:"patch"`
	Prune    bool           `json:"prune" yaml:"prune"`
	Reweight float64        `json:"reweight" yaml:"reweight"`
	Merge    bool           `json:"merge" yaml:"merge"`
	Reason   string         `json:"reason" yaml:"reason"`
}

type Table struct {
	Rules []Rule `json:"rules" yaml:"rules"`
}

type Engine struct {
	mu      sync.Mutex
	table   Table
	applied map[string]core.DeltaDef
}

func NewEngine(table Table) (*Engine, error) {
	if len(table.Rules) > MaxRules {
		return nil, core.NewFailure("META_TABLE_TOO_LARGE", "meta table exceeds bounded rule count", map[string]any{"max_rules": MaxRules}, false)
	}
	for i := 0; i < len(table.Rules) && i < MaxRules; i++ {
		table.Rules[i] = normalizeRule(table.Rules[i], i)
		rule := table.Rules[i]
		if rule.ID == "" || rule.When == "" {
			return nil, core.NewFailure("META_RULE_INVALID", "meta rule requires id and when", map[string]any{"index": i}, false)
		}
	}
	return &Engine{table: table, applied: map[string]core.DeltaDef{}}, nil
}

func normalizeRule(rule Rule, index int) Rule {
	if rule.ID == "" {
		rule.ID = "meta-rule-" + strconv.Itoa(index+1)
	}
	if rule.When == "" && rule.If != "" {
		rule.When = rule.If
	}
	if rule.Patch == nil {
		rule.Patch = map[string]any{}
	}
	if rule.Prune {
		rule.Patch["prune"] = true
	}
	if rule.Reweight != 0 {
		rule.Patch["reweight"] = rule.Reweight
	}
	if rule.Merge {
		rule.Patch["merge"] = true
	}
	if rule.Reason == "" {
		rule.Reason = rule.When
	}
	return rule
}

func (e *Engine) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "meta.engine", RuntimeCap: 25 * time.Millisecond, MemoryCapMiB: 4}
}

// Consume converts bounded step logs into bounded delta definition proposals.
func (e *Engine) Consume(logs []core.StepLog, result core.Result) ([]core.DeltaDef, error) {
	if len(logs) > core.MaxStepLogs {
		return nil, core.NewFailure("META_LOGS_TOO_LARGE", "step logs exceed bounded count", map[string]any{"max_logs": core.MaxStepLogs}, false)
	}
	deltas := make([]core.DeltaDef, 0, MaxDeltaDefs)
	for i := 0; i < len(e.table.Rules) && i < MaxRules; i++ {
		rule := e.table.Rules[i]
		if !metaRuleMatches(rule.When, logs, result) {
			continue
		}
		patch := make(map[string]any, len(rule.Patch))
		for key, value := range rule.Patch {
			if len(patch) >= core.MaxPayloadKeys {
				return nil, core.NewFailure("META_PATCH_TOO_LARGE", "meta patch exceeds bounded key count", nil, false)
			}
			patch[key] = value
		}
		deltas = append(deltas, core.DeltaDef{ID: result.ID + ":" + rule.ID, When: rule.When, Patch: patch, Reason: rule.Reason})
		if len(deltas) >= MaxDeltaDefs {
			break
		}
	}
	return deltas, nil
}

// Apply records safe delta definitions locally; callers own durable storage.
func (e *Engine) Apply(deltas []core.DeltaDef) error {
	if len(deltas) > MaxDeltaDefs {
		return core.NewFailure("META_DELTA_TOO_LARGE", "meta delta batch exceeds bound", map[string]any{"max_delta_defs": MaxDeltaDefs}, false)
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	for i := 0; i < len(deltas) && i < MaxDeltaDefs; i++ {
		delta := deltas[i]
		if delta.ID == "" || len(delta.Patch) > core.MaxPayloadKeys {
			return core.NewFailure("META_DELTA_INVALID", "delta definition requires id and bounded patch", map[string]any{"index": i}, false)
		}
		if len(e.applied) >= MaxAppliedDefs {
			return core.NewFailure("META_APPLY_FULL", "applied meta definition store reached bounded capacity", map[string]any{"max_applied": MaxAppliedDefs}, true)
		}
		e.applied[delta.ID] = delta
	}
	return nil
}

func metaRuleMatches(when string, logs []core.StepLog, result core.Result) bool {
	switch when {
	case "always":
		return true
	case "result.ok":
		return result.Status == "ok"
	case "result.error":
		return result.Status == "error"
	case "stage.action":
		for i := 0; i < len(logs) && i < core.MaxStepLogs; i++ {
			if logs[i].Stage == "action" {
				return true
			}
		}
		return false
	default:
		return metricRuleMatches(when, result)
	}
}

func metricRuleMatches(when string, result core.Result) bool {
	ops := []string{">=", "<=", ">", "<", "="}
	for i := 0; i < len(ops); i++ {
		op := ops[i]
		parts := strings.SplitN(when, op, 2)
		if len(parts) != 2 {
			continue
		}
		left := strings.TrimSpace(parts[0])
		right := strings.TrimSpace(parts[1])
		actual, ok := numericOutput(left, result)
		if !ok {
			return false
		}
		expected, err := strconv.ParseFloat(right, 64)
		if err != nil {
			return false
		}
		return compareFloat(actual, expected, op)
	}
	return false
}

func numericOutput(name string, result core.Result) (float64, bool) {
	value, ok := result.Output[strings.TrimSpace(name)]
	if !ok {
		return 0, false
	}
	switch typed := value.(type) {
	case float64:
		return typed, true
	case float32:
		return float64(typed), true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case int32:
		return float64(typed), true
	default:
		return 0, false
	}
}

func compareFloat(actual float64, expected float64, op string) bool {
	switch op {
	case ">=":
		return actual >= expected
	case "<=":
		return actual <= expected
	case ">":
		return actual > expected
	case "<":
		return actual < expected
	case "=":
		return actual == expected
	default:
		return false
	}
}
