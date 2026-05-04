package trisca

import (
	"context"
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

func TestScoreDeterministic(t *testing.T) {
	engine, err := New(Config{})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	input := []shared.Primitive{{ID: "p1", Value: 8, Quality: 0.5, Cost: 2, Time: 2, Influence: 1}}

	first, err := engine.Score(context.Background(), input)
	if err != nil {
		t.Fatalf("Score() first error = %v", err)
	}
	second, err := engine.Score(context.Background(), input)
	if err != nil {
		t.Fatalf("Score() second error = %v", err)
	}
	if len(first) != 1 || len(second) != 1 {
		t.Fatalf("len(first) = %d, len(second) = %d, want 1", len(first), len(second))
	}
	if first[0] != second[0] {
		t.Fatalf("Score() not deterministic: %#v != %#v", first[0], second[0])
	}
	if first[0].Score != 1 {
		t.Fatalf("score = %v, want 1", first[0].Score)
	}
}

func TestScoreRejectsZeroDenominator(t *testing.T) {
	engine, err := New(Config{})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	_, err = engine.Score(context.Background(), []shared.Primitive{{ID: "p1", Value: 1, Quality: 1}})
	if err == nil {
		t.Fatal("Score() error = nil, want denominator failure")
	}
}
