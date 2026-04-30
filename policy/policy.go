package policy

import (
	"strconv"
	"strings"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

const (
	MaxRules            = 64
	DefaultPolicyCapMiB = 4
)

type Rule struct {
	ID         string         `json:"id" yaml:"id"`
	When       string         `json:"when" yaml:"when"`
	Action     string         `json:"action" yaml:"action"`
	Params     map[string]any `json:"params" yaml:"params"`
	Priority   float64        `json:"priority" yaml:"priority"`
	Confidence float64        `json:"confidence" yaml:"confidence"`
	EV         float64        `json:"ev" yaml:"ev"`
	Cost       float64        `json:"cost" yaml:"cost"`
}

type Table struct {
	ID       string `json:"id" yaml:"id"`
	Rules    []Rule `json:"rules" yaml:"rules"`
	Policies []Rule `json:"policies" yaml:"policies"`
}

type Engine struct {
	table Table
}

func NewEngine(table Table) (Engine, error) {
	table = normalizeTable(table)
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
		confidence := ruleConfidence(rule)
		ev := ruleEV(rule)
		score := confidence*ev - rule.Cost
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
				Confidence: confidence,
				EV:         ev,
				Cost:       rule.Cost,
				Score:      score,
				Noop:       false,
			}
			matched = true
		}
	}
	return best, nil
}

func normalizeTable(table Table) Table {
	if len(table.Rules) == 0 && len(table.Policies) > 0 {
		table.Rules = table.Policies
	}
	return table
}

func ruleConfidence(rule Rule) float64 {
	if rule.Confidence > 0 {
		return rule.Confidence
	}
	if rule.Priority > 0 {
		return rule.Priority
	}
	return 1
}

func ruleEV(rule Rule) float64 {
	if rule.EV > 0 {
		return rule.EV
	}
	return 1
}

func matches(when string, resolved core.ResolvedEvent, trisca core.TRISCAOutput) bool {
	if strings.TrimSpace(when) == "always" {
		return true
	}
	clauses := strings.Split(when, "&&")
	if len(clauses) > 8 {
		return false
	}
	for i := 0; i < len(clauses); i++ {
		if !matchesClause(strings.TrimSpace(clauses[i]), resolved, trisca) {
			return false
		}
	}
	return true
}

func matchesClause(clause string, resolved core.ResolvedEvent, trisca core.TRISCAOutput) bool {
	if strings.HasPrefix(clause, "kind=") {
		return resolved.Event.Kind == strings.TrimPrefix(clause, "kind=")
	}
	ops := []string{">=", "<=", ">", "<", "="}
	for i := 0; i < len(ops); i++ {
		op := ops[i]
		parts := strings.SplitN(clause, op, 2)
		if len(parts) != 2 {
			continue
		}
		left := strings.TrimSpace(parts[0])
		right := strings.TrimSpace(parts[1])
		actual, ok := metricValue(left, trisca)
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

func metricValue(name string, trisca core.TRISCAOutput) (float64, bool) {
	name = strings.TrimPrefix(strings.TrimSpace(name), "s.")
	switch name {
	case "confidence":
		return trisca.Confidence, true
	case "structure":
		return trisca.Vector.Structure, true
	case "entropy":
		return trisca.Vector.Entropy, true
	case "inequality":
		return trisca.Vector.Inequality, true
	case "temporal":
		return trisca.Vector.Temporal, true
	case "efficiency":
		return trisca.Vector.Efficiency, true
	case "signal_density":
		return trisca.Vector.SignalDensity, true
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
