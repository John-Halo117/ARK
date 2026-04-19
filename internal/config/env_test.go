package config

import "testing"

func TestStringAndFloat64Fallbacks(t *testing.T) {
	t.Setenv("CFG_TEXT", "value")
	t.Setenv("CFG_FLOAT", "2.5")
	t.Setenv("CFG_BAD_FLOAT", "x")

	if got := String("CFG_TEXT", "fallback"); got != "value" {
		t.Fatalf("String expected value, got %q", got)
	}
	if got := String("CFG_MISSING", "fallback"); got != "fallback" {
		t.Fatalf("String expected fallback, got %q", got)
	}
	if got := Float64("CFG_FLOAT", 1.0); got != 2.5 {
		t.Fatalf("Float64 expected 2.5, got %v", got)
	}
	if got := Float64("CFG_BAD_FLOAT", 1.0); got != 1.0 {
		t.Fatalf("Float64 expected fallback for bad float, got %v", got)
	}
}
