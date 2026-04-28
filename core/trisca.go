package core

import (
	"math"
	"time"
)

const MaxTRISCATrace = 6

type DeterministicTRISCA struct {
	RuntimeCap   time.Duration
	MemoryCapMiB int
}

func NewDeterministicTRISCA() DeterministicTRISCA {
	return DeterministicTRISCA{RuntimeCap: 25 * time.Millisecond, MemoryCapMiB: 4}
}

func (t DeterministicTRISCA) Health() HealthStatus {
	cap := t.RuntimeCap
	if cap <= 0 {
		cap = 25 * time.Millisecond
	}
	mem := t.MemoryCapMiB
	if mem <= 0 {
		mem = 4
	}
	return HealthStatus{Status: "ok", Module: "core.trisca", RuntimeCap: cap, MemoryCapMiB: mem}
}

// Compute is the single deterministic TRISCA path for SD-ARK.
func (t DeterministicTRISCA) Compute(resolved ResolvedEvent) (TRISCAOutput, error) {
	if err := ValidateEvent(resolved.Event); err != nil {
		return TRISCAOutput{}, err
	}
	obs := resolved.Event.Observations
	if len(obs) > MaxObservations {
		return TRISCAOutput{}, NewFailure("TRISCA_INPUT_TOO_LARGE", "observation count exceeds S[6] bound", map[string]any{"max_observations": MaxObservations}, false)
	}
	values := make([]float64, MaxObservations)
	for i := 0; i < len(obs) && i < MaxObservations; i++ {
		if math.IsNaN(obs[i]) || math.IsInf(obs[i], 0) {
			return TRISCAOutput{}, NewFailure("TRISCA_INPUT_INVALID", "observation must be finite", map[string]any{"index": i}, false)
		}
		values[i] = clamp01(obs[i])
	}

	structure := mean(values, 0, MaxObservations)
	entropy := normalizedEntropy(values)
	inequality := boundedInequality(values)
	temporal := temporalScore(resolved.Event.OccurredAt, resolved.ResolvedAt)
	efficiency := clamp01(1 - (entropy+inequality)/2)
	signalDensity := clamp01(nonZeroRatio(values))
	confidence := clamp01((structure + efficiency + signalDensity + (1 - inequality)) / 4)

	trace := make([]string, 0, MaxTRISCATrace)
	trace = append(trace, "normalize")
	trace = append(trace, "structure")
	trace = append(trace, "entropy")
	trace = append(trace, "inequality")
	trace = append(trace, "temporal")
	trace = append(trace, "efficiency_signal")

	return TRISCAOutput{
		Vector: SVector{
			Structure:     structure,
			Entropy:       entropy,
			Inequality:    inequality,
			Temporal:      temporal,
			Efficiency:    efficiency,
			SignalDensity: signalDensity,
		},
		Confidence: confidence,
		Trace:      trace,
	}, nil
}

func mean(values []float64, start int, limit int) float64 {
	total := 0.0
	count := 0
	for i := start; i < len(values) && i < limit; i++ {
		total += values[i]
		count++
	}
	if count == 0 {
		return 0
	}
	return total / float64(count)
}

func normalizedEntropy(values []float64) float64 {
	total := 0.0
	for i := 0; i < len(values) && i < MaxObservations; i++ {
		total += values[i]
	}
	if total <= 0 {
		return 0
	}
	entropy := 0.0
	for i := 0; i < len(values) && i < MaxObservations; i++ {
		p := values[i] / total
		if p > 0 {
			entropy -= p * math.Log(p)
		}
	}
	return clamp01(entropy / math.Log(MaxObservations))
}

func boundedInequality(values []float64) float64 {
	minValue := 1.0
	maxValue := 0.0
	for i := 0; i < len(values) && i < MaxObservations; i++ {
		if values[i] < minValue {
			minValue = values[i]
		}
		if values[i] > maxValue {
			maxValue = values[i]
		}
	}
	return clamp01(maxValue - minValue)
}

func temporalScore(occurredAt time.Time, resolvedAt time.Time) float64 {
	if occurredAt.IsZero() || resolvedAt.IsZero() {
		return 1
	}
	age := resolvedAt.Sub(occurredAt)
	if age < 0 {
		age = -age
	}
	return clamp01(1 / (1 + age.Seconds()))
}

func nonZeroRatio(values []float64) float64 {
	count := 0
	for i := 0; i < len(values) && i < MaxObservations; i++ {
		if values[i] > 0 {
			count++
		}
	}
	return float64(count) / float64(MaxObservations)
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}
