package valor

import (
	"context"
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

func TestRunProducesDeterministicActions(t *testing.T) {
	core, err := New(Config{SortKept: true})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	input := []shared.Score{
		{PrimitiveID: "a", Value: 1, Quality: 1, Cost: 1, Time: 1, Influence: 4, Score: 0.8},
		{PrimitiveID: "b", Value: 1, Quality: 1, Cost: 1, Time: 1, Influence: 1, Score: 0.4},
		{PrimitiveID: "c", Value: 1, Quality: 1, Cost: 1, Time: 1, Influence: 1, Score: 0.2},
	}

	first, err := core.Run(context.Background(), input)
	if err != nil {
		t.Fatalf("Run() first error = %v", err)
	}
	second, err := core.Run(context.Background(), input)
	if err != nil {
		t.Fatalf("Run() second error = %v", err)
	}
	if len(first.Actions) != len(second.Actions) {
		t.Fatalf("action counts differ: %d != %d", len(first.Actions), len(second.Actions))
	}
	for index := 0; index < len(first.Actions) && index < len(second.Actions); index++ {
		if first.Actions[index] != second.Actions[index] {
			t.Fatalf("action[%d] differs: %#v != %#v", index, first.Actions[index], second.Actions[index])
		}
	}
}

func TestRunRejectsInvalidScore(t *testing.T) {
	core, err := New(Config{})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	_, err = core.Run(context.Background(), []shared.Score{{PrimitiveID: "bad", Cost: -1}})
	if err == nil {
		t.Fatal("Run() error = nil, want invalid score failure")
	}
}

func TestRunAcceptsEmptyInput(t *testing.T) {
	core, err := New(Config{})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	output, err := core.Run(context.Background(), nil)
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if output.Status != "ok" || len(output.Actions) != 0 {
		t.Fatalf("output = %#v, want ok with no actions", output)
	}
}
