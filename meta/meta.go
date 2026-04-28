package meta

import (
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
	ID     string         `json:"id"`
	When   string         `json:"when"`
	Patch  map[string]any `json:"patch"`
	Reason string         `json:"reason"`
}

type Table struct {
	Rules []Rule `json:"rules"`
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
		rule := table.Rules[i]
		if rule.ID == "" || rule.When == "" {
			return nil, core.NewFailure("META_RULE_INVALID", "meta rule requires id and when", map[string]any{"index": i}, false)
		}
	}
	return &Engine{table: table, applied: map[string]core.DeltaDef{}}, nil
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
		return false
	}
}
