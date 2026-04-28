package core

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"
)

const (
	MaxPayloadKeys       = 64
	MaxObservations      = 6
	MaxEvidenceItems     = 16
	MaxStepLogs          = 16
	DefaultStepTimeout   = 250 * time.Millisecond
	DefaultStepMemoryMiB = 16
)

// Failure is the standard ARK structured failure object used across SD-ARK.
type Failure struct {
	Status      string         `json:"status"`
	ErrorCode   string         `json:"error_code"`
	Reason      string         `json:"reason"`
	Context     map[string]any `json:"context"`
	Recoverable bool           `json:"recoverable"`
}

func NewFailure(code string, reason string, context map[string]any, recoverable bool) Failure {
	if context == nil {
		context = map[string]any{}
	}
	return Failure{Status: "error", ErrorCode: code, Reason: reason, Context: context, Recoverable: recoverable}
}

func (f Failure) Error() string {
	return fmt.Sprintf("%s: %s", f.ErrorCode, f.Reason)
}

// HealthStatus exposes bounded module readiness without hidden process state.
type HealthStatus struct {
	Status       string        `json:"status"`
	Module       string        `json:"module"`
	RuntimeCap   time.Duration `json:"runtime_cap"`
	MemoryCapMiB int           `json:"memory_cap_mib"`
}

type Event struct {
	ID           string         `json:"id"`
	Kind         string         `json:"kind"`
	Payload      map[string]any `json:"payload"`
	Observations []float64      `json:"observations,omitempty"`
	Evidence     []Evidence     `json:"evidence,omitempty"`
	OccurredAt   time.Time      `json:"occurred_at"`
}

type Evidence struct {
	Prior       float64 `json:"prior"`
	Likelihood float64 `json:"likelihood"`
}

type ResolvedEvent struct {
	Event      Event     `json:"event"`
	Delta     Delta     `json:"delta"`
	ResolvedAt time.Time `json:"resolved_at"`
}

type Delta struct {
	Kind    string         `json:"kind"`
	Values  map[string]any `json:"values"`
	LogOdds float64        `json:"log_odds"`
}

type SVector struct {
	Structure     float64 `json:"structure"`
	Entropy       float64 `json:"entropy"`
	Inequality    float64 `json:"inequality"`
	Temporal      float64 `json:"temporal"`
	Efficiency    float64 `json:"efficiency"`
	SignalDensity float64 `json:"signal_density"`
}

type TRISCAOutput struct {
	Vector     SVector `json:"s"`
	Confidence float64 `json:"confidence"`
	Trace      []string `json:"trace"`
}

type Intent struct {
	ID         string         `json:"id"`
	Action     string         `json:"action"`
	Params     map[string]any `json:"params"`
	Confidence float64        `json:"confidence"`
	EV         float64        `json:"ev"`
	Cost       float64        `json:"cost"`
	Score      float64        `json:"score"`
	Noop       bool           `json:"noop"`
}

type Result struct {
	ID      string         `json:"id"`
	Status  string         `json:"status"`
	Action  string         `json:"action"`
	Output  map[string]any `json:"output"`
	Failure *Failure       `json:"failure,omitempty"`
}

type DeltaDef struct {
	ID     string         `json:"id"`
	When   string         `json:"when"`
	Patch  map[string]any `json:"patch"`
	Reason string         `json:"reason"`
}

type StepInput struct {
	Event Event `json:"event"`
}

type StepOutput struct {
	Status   string       `json:"status"`
	EventID  string       `json:"event_id"`
	Resolved ResolvedEvent `json:"resolved"`
	TRISCA   TRISCAOutput  `json:"trisca"`
	Intent   Intent        `json:"intent"`
	Result   Result        `json:"result"`
	Meta     []DeltaDef    `json:"meta"`
	Logs     []StepLog     `json:"logs"`
	Failure  *Failure      `json:"failure,omitempty"`
}

type StepLog struct {
	Stage   string         `json:"stage"`
	Message string         `json:"message"`
	Context map[string]any `json:"context,omitempty"`
}

type Resolver interface {
	Resolve(Event) (ResolvedEvent, error)
	Health() HealthStatus
}

type TRISCAEngine interface {
	Compute(ResolvedEvent) (TRISCAOutput, error)
	Health() HealthStatus
}

type PolicyEngine interface {
	Evaluate(ResolvedEvent, TRISCAOutput) (Intent, error)
	Health() HealthStatus
}

type ActionExecutor interface {
	Exec(context.Context, Intent) Result
	Health() HealthStatus
}

type MetaEngine interface {
	Consume([]StepLog, Result) ([]DeltaDef, error)
	Apply([]DeltaDef) error
	Health() HealthStatus
}

type StepRuntime struct {
	Resolver Resolver
	TRISCA   TRISCAEngine
	Policy   PolicyEngine
	Action   ActionExecutor
	Meta     MetaEngine
	Timeout  time.Duration
}

func (r StepRuntime) Health() HealthStatus {
	timeout := r.Timeout
	if timeout <= 0 {
		timeout = DefaultStepTimeout
	}
	return HealthStatus{Status: "ok", Module: "core.step", RuntimeCap: timeout, MemoryCapMiB: DefaultStepMemoryMiB}
}

// Step executes the single SD-ARK loop:
// Event -> Resolve(delta) -> TRISCA -> S[6] -> Policy -> Intent -> Action -> Result -> Meta(delta_defs).
func (r StepRuntime) Step(ctx context.Context, input StepInput) StepOutput {
	logs := make([]StepLog, 0, MaxStepLogs)
	appendLog := func(stage string, message string, fields map[string]any) {
		if len(logs) < MaxStepLogs {
			logs = append(logs, StepLog{Stage: stage, Message: message, Context: fields})
		}
	}

	if err := r.validate(); err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Logs: logs, Failure: &failure}
	}
	if err := ValidateEvent(input.Event); err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Logs: logs, Failure: &failure}
	}

	timeout := r.Timeout
	if timeout <= 0 {
		timeout = DefaultStepTimeout
	}
	stepCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	appendLog("event", "accepted", map[string]any{"kind": input.Event.Kind})
	resolved, err := r.Resolver.Resolve(input.Event)
	if err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Logs: logs, Failure: &failure}
	}
	appendLog("resolve", "delta resolved", map[string]any{"delta_kind": resolved.Delta.Kind})

	triscaOut, err := r.TRISCA.Compute(resolved)
	if err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Resolved: resolved, Logs: logs, Failure: &failure}
	}
	appendLog("trisca", "s vector computed", map[string]any{"confidence": triscaOut.Confidence})

	intent, err := r.Policy.Evaluate(resolved, triscaOut)
	if err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Resolved: resolved, TRISCA: triscaOut, Logs: logs, Failure: &failure}
	}
	appendLog("policy", "intent selected", map[string]any{"action": intent.Action, "score": intent.Score})

	result := r.Action.Exec(stepCtx, intent)
	appendLog("action", "result produced", map[string]any{"status": result.Status, "action": result.Action})
	if result.Failure != nil {
		return StepOutput{Status: "error", EventID: input.Event.ID, Resolved: resolved, TRISCA: triscaOut, Intent: intent, Result: result, Logs: logs, Failure: result.Failure}
	}

	deltas, err := r.Meta.Consume(logs, result)
	if err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Resolved: resolved, TRISCA: triscaOut, Intent: intent, Result: result, Logs: logs, Failure: &failure}
	}
	if err := r.Meta.Apply(deltas); err != nil {
		failure := failureFromError(err)
		return StepOutput{Status: "error", EventID: input.Event.ID, Resolved: resolved, TRISCA: triscaOut, Intent: intent, Result: result, Meta: deltas, Logs: logs, Failure: &failure}
	}
	appendLog("meta", "delta definitions applied", map[string]any{"count": len(deltas)})

	return StepOutput{Status: "ok", EventID: input.Event.ID, Resolved: resolved, TRISCA: triscaOut, Intent: intent, Result: result, Meta: deltas, Logs: logs}
}

func (r StepRuntime) validate() error {
	if r.Resolver == nil || r.TRISCA == nil || r.Policy == nil || r.Action == nil || r.Meta == nil {
		return NewFailure("STEP_RUNTIME_INVALID", "step runtime dependencies must be explicit", nil, false)
	}
	return nil
}

func ValidateEvent(event Event) error {
	if event.ID == "" {
		return NewFailure("EVENT_ID_REQUIRED", "event id is required", nil, false)
	}
	if event.Kind == "" {
		return NewFailure("EVENT_KIND_REQUIRED", "event kind is required", map[string]any{"event_id": event.ID}, false)
	}
	if len(event.Payload) > MaxPayloadKeys {
		return NewFailure("EVENT_PAYLOAD_TOO_LARGE", "event payload exceeds bounded key count", map[string]any{"max_keys": MaxPayloadKeys}, false)
	}
	if len(event.Observations) > MaxObservations {
		return NewFailure("EVENT_OBSERVATIONS_TOO_LARGE", "event observations exceed S[6] input bound", map[string]any{"max_observations": MaxObservations}, false)
	}
	if len(event.Evidence) > MaxEvidenceItems {
		return NewFailure("EVENT_EVIDENCE_TOO_LARGE", "event evidence exceeds update bound", map[string]any{"max_evidence": MaxEvidenceItems}, false)
	}
	return nil
}

type DefaultResolver struct{}

func (DefaultResolver) Health() HealthStatus {
	return HealthStatus{Status: "ok", Module: "core.resolver", RuntimeCap: 25 * time.Millisecond, MemoryCapMiB: 4}
}

func (DefaultResolver) Resolve(event Event) (ResolvedEvent, error) {
	if err := ValidateEvent(event); err != nil {
		return ResolvedEvent{}, err
	}
	values := make(map[string]any, len(event.Payload)+1)
	keys := make([]string, 0, len(event.Payload))
	for key := range event.Payload {
		if len(keys) >= MaxPayloadKeys {
			return ResolvedEvent{}, NewFailure("EVENT_PAYLOAD_TOO_LARGE", "payload key bound exceeded during resolve", nil, false)
		}
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for i := 0; i < len(keys) && i < MaxPayloadKeys; i++ {
		values[keys[i]] = event.Payload[keys[i]]
	}
	values["event_kind"] = event.Kind

	logOdds := 0.0
	for i := 0; i < len(event.Evidence) && i < MaxEvidenceItems; i++ {
		next, err := UpdateLogOdds(logOdds, event.Evidence[i].Prior, event.Evidence[i].Likelihood)
		if err != nil {
			return ResolvedEvent{}, err
		}
		logOdds = next
	}
	return ResolvedEvent{
		Event:      event,
		Delta:     Delta{Kind: "event_delta", Values: values, LogOdds: logOdds},
		ResolvedAt: event.OccurredAt.UTC(),
	}, nil
}

func failureFromError(err error) Failure {
	var failure Failure
	if errors.As(err, &failure) {
		return failure
	}
	return NewFailure("UNEXPECTED_ERROR", err.Error(), nil, true)
}
