package policy

import (
	"strings"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

const (
	MaxRules            = 64
	DefaultPolicyCapMiB = 4
)

type Rule struct {
	ID         string         `json:"id"`
	When       string         `json:"when"`
	Action     string         `json:"action"`
	Params     map[string]any `json:"params"`
	Confidence float64        `json:"confidence"`
	EV         float64        `json:"ev"`
	Cost       float64        `json:"cost"`
}

type Table struct {
	Rules []Rule `json:"rules"`
}

type Engine struct {
	table Table
}

func NewEngine(table Table) (Engine, error) {
	if len(table.Rules) > MaxRules {
		return Engine{}, core.NewFailure("POLICY_TABLE_TOO_LARGE", "policy table exceeds bounded rule count", map[string]any{"max_rules": MaxRules}, false)
	}
	for i := 0; i < len(table.Rules) && i < MaxRules; i++ {
		rule := table.Rules[i]
		if rule.ID == "" || rule.Action == "" || rule.When == "" {
			return Engine{}, core.NewFailure("POLICY_RULE_INVALID", "policy rule requires id, when, and action", map[string]any{"index": i}, false)
		}
	}
	return Engine{table: table}, nil
}

func (e Engine) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "policy.table", RuntimeCap: 25 * time.Millisecond, MemoryCapMiB: DefaultPolicyCapMiB}
}

// Evaluate is table-driven and scores matches as confidence*EV-cost.
func (e Engine) Evaluate(resolved core.ResolvedEvent, trisca core.TRISCAOutput) (core.Intent, error) {
	best := core.Intent{ID: resolved.Event.ID + ":noop", Action: "noop", Params: map[string]any{}, Noop: true}
	matched := false
	for i := 0; i < len(e.table.Rules) && i < MaxRules; i++ {
		rule := e.table.Rules[i]
		if !matches(rule.When, resolved, trisca) {
			continue
		}
		score := rule.Confidence*rule.EV - rule.Cost
		if !matched || score > best.Score {
			params := make(map[string]any, len(rule.Params))
			for key, value := range rule.Params {
				if len(params) >= core.MaxPayloadKeys {
					return core.Intent{}, core.NewFailure("POLICY_PARAMS_TOO_LARGE", "policy params exceed bounded key count", nil, false)
				}
				params[key] = value
			}
			best = core.Intent{
				ID:         resolved.Event.ID + ":" + rule.ID,
				Action:     rule.Action,
				Params:     params,
				Confidence: rule.Confidence,
				EV:         rule.EV,
				Cost:       rule.Cost,
				Score:      score,
				Noop:       false,
			}
			matched = true
		}
	}
	return best, nil
}

func matches(when string, resolved core.ResolvedEvent, trisca core.TRISCAOutput) bool {
	switch {
	case when == "always":
		return true
	case strings.HasPrefix(when, "kind="):
		return resolved.Event.Kind == strings.TrimPrefix(when, "kind=")
	case strings.HasPrefix(when, "confidence>="):
		threshold, ok := parseKnownThreshold(strings.TrimPrefix(when, "confidence>="))
		return ok && trisca.Confidence >= threshold
	case strings.HasPrefix(when, "s.entropy<="):
		threshold, ok := parseKnownThreshold(strings.TrimPrefix(when, "s.entropy<="))
		return ok && trisca.Vector.Entropy <= threshold
	default:
		return false
	}
}

func parseKnownThreshold(raw string) (float64, bool) {
	switch raw {
	case "0":
		return 0, true
	case "0.25":
		return 0.25, true
	case "0.5":
		return 0.5, true
	case "0.75":
		return 0.75, true
	case "1":
		return 1, true
	default:
		return 0, false
	}
}
