package core_test

import (
	"context"
	"reflect"
	"testing"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

func TestDeterministicTRISCA(t *testing.T) {
	engine := core.NewDeterministicTRISCA()
	event := core.Event{
		ID:           "evt-1",
		Kind:         "metric",
		Payload:      map[string]any{"source": "test"},
		Observations: []float64{0.2, 0.4, 0.6, 0.8, 0.1, 0.3},
		OccurredAt:   time.Unix(10, 0).UTC(),
	}
	resolved := core.ResolvedEvent{Event: event, ResolvedAt: event.OccurredAt}
	first, err := engine.Compute(resolved)
	if err != nil {
		t.Fatalf("first compute failed: %v", err)
	}
	second, err := engine.Compute(resolved)
	if err != nil {
		t.Fatalf("second compute failed: %v", err)
	}
	if !reflect.DeepEqual(first, second) {
		t.Fatalf("TRISCA output is not deterministic: %#v != %#v", first, second)
	}
	if len(first.Trace) != core.MaxTRISCATrace {
		t.Fatalf("trace length = %d, want %d", len(first.Trace), core.MaxTRISCATrace)
	}
}

func TestStepRejectsUnboundedPayload(t *testing.T) {
	payload := map[string]any{}
	for i := 0; i < core.MaxPayloadKeys+1; i++ {
		payload[string(rune('a'+i))] = i
	}
	output := core.StepRuntime{}.Step(context.Background(), core.StepInput{Event: core.Event{ID: "evt", Kind: "overflow", Payload: payload}})
	if output.Failure == nil || output.Failure.ErrorCode != "STEP_RUNTIME_INVALID" {
		t.Fatalf("failure = %#v, want runtime dependency failure before payload processing", output.Failure)
	}
}
