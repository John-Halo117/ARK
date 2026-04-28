package runtime_test

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
	"github.com/John-Halo117/ARK/arkfield/runtime"
)

func TestReplayHarnessDeterministicIdempotentBounded(t *testing.T) {
	compiled, err := runtime.Compile(runtime.DefaultDefinitionPaths(filepath.Join("..", "definitions")))
	if err != nil {
		t.Fatalf("compile failed: %v", err)
	}
	stepRuntime := core.NewDefaultRuntime(
		core.DefaultResolver{},
		core.NewDeterministicTRISCA(),
		compiled.Policy,
		compiled.Action,
		compiled.Meta,
	)
	event := core.Event{
		ID:           "evt-replay-1",
		Kind:         "metric",
		Payload:      map[string]any{"source": "replay"},
		Observations: []float64{0.9, 0.8, 0.7, 0.6, 0.5, 0.4},
		OccurredAt:   time.Unix(42, 0).UTC(),
	}
	first := stepRuntime.Step(context.Background(), core.StepInput{Event: event})
	second := stepRuntime.Step(context.Background(), core.StepInput{Event: event})
	if first.Failure != nil {
		t.Fatalf("first replay failed: %#v", first.Failure)
	}
	if second.Failure != nil {
		t.Fatalf("second replay failed: %#v", second.Failure)
	}
	if !sameTRISCA(first.TRISCA, second.TRISCA) {
		t.Fatalf("TRISCA differed across replay")
	}
	if first.Result.ID != second.Result.ID || first.Result.Status != second.Result.Status {
		t.Fatalf("idempotent action mismatch: %#v != %#v", first.Result, second.Result)
	}
	if len(first.Meta) > 8 || len(second.Meta) > 8 {
		t.Fatalf("meta delta exceeded bound")
	}
}

func sameTRISCA(left core.TRISCAOutput, right core.TRISCAOutput) bool {
	return left.Vector == right.Vector && left.Confidence == right.Confidence
}
