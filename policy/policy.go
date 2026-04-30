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
	Confidence float64        `json:"confidence" yaml:"confidence"`
	EV         float64        `json:"ev" yaml:"ev"`
	Cost       float64        `json:"cost" yaml:"cost"`
	Priority   float64        `json:"priority" yaml:"priority"`
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
		score := scoreRule(rule)
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
	clauses := strings.Split(when, "&&")
	for i := 0; i < len(clauses) && i < 8; i++ {
		if !matchesClause(strings.TrimSpace(clauses[i]), resolved, trisca) {
			return false
		}
	}
	return len(clauses) > 0
}

func normalizeTable(table Table) Table {
	if len(table.Rules) == 0 && len(table.Policies) > 0 {
		table.Rules = table.Policies
	}
	return table
}

func scoreRule(rule Rule) float64 {
	confidence := rule.Confidence
	if confidence == 0 {
		confidence = rule.Priority
	}
	if confidence == 0 {
		confidence = 1
	}
	ev := rule.EV
	if ev == 0 {
		ev = 1
	}
	return confidence*ev - rule.Cost
}

func matchesClause(clause string, resolved core.ResolvedEvent, trisca core.TRISCAOutput) bool {
	if clause == "always" {
		return true
	}
	if strings.HasPrefix(clause, "kind=") {
		return resolved.Event.Kind == strings.TrimSpace(strings.TrimPrefix(clause, "kind="))
	}
	for _, op := range []string{">=", "<=", ">", "<", "="} {
		parts := strings.Split(clause, op)
		if len(parts) != 2 {
			continue
		}
		left := strings.TrimSpace(strings.TrimPrefix(parts[0], "s."))
		right, err := strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
		if err != nil {
			return false
		}
		value, ok := metricValue(left, trisca)
		if !ok {
			return false
		}
		switch op {
		case ">=":
			return value >= right
		case "<=":
			return value <= right
		case ">":
			return value > right
		case "<":
			return value < right
		case "=":
			return value == right
		}
	}
	return false
}

func metricValue(name string, trisca core.TRISCAOutput) (float64, bool) {
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
