package trisca

import (
	"context"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

const (
	DefaultRuntimeCap   = 25 * time.Millisecond
	DefaultMemoryCapMiB = 4
	DefaultMaxInputs    = shared.MaxPrimitiveCount
)

type Theta struct {
	ValueWeight   float64 `json:"value_weight"`
	QualityWeight float64 `json:"quality_weight"`
	CostWeight    float64 `json:"cost_weight"`
	TimeWeight    float64 `json:"time_weight"`
	ScoreScale    float64 `json:"score_scale"`
}

type Config struct {
	Theta        Theta
	MaxInputs    int
	RuntimeCap   time.Duration
	MemoryCapMiB int
}

type TRISCA struct {
	cfg Config
}

func New(cfg Config) (TRISCA, error) {
	normalized := normalizeConfig(cfg)
	if err := validateConfig(normalized); err != nil {
		return TRISCA{}, err
	}
	return TRISCA{cfg: normalized}, nil
}

func (t TRISCA) Health() shared.HealthStatus {
	cfg := normalizeConfig(t.cfg)
	return shared.HealthStatus{Status: "ok", Module: "internal.trisca", RuntimeCap: cfg.RuntimeCap, MemoryCapMiB: cfg.MemoryCapMiB}
}

// Score input schema: context.Context and []shared.Primitive.
// Output schema: []shared.Score or shared.Failure error.
// Runtime constraint: O(n), capped by Config.MaxInputs and Config.RuntimeCap.
// Memory assumption: O(n), capped by Config.MaxInputs result allocation.
// Failure cases: canceled context, invalid config, invalid primitive, zero denominator, oversized input.
// Determinism: same primitives and theta produce identical scores.
func (t TRISCA) Score(ctx context.Context, primitives []shared.Primitive) ([]shared.Score, error) {
	cfg := normalizeConfig(t.cfg)
	if ctx == nil {
		return nil, shared.NewFailure("TRISCA_CONTEXT_REQUIRED", "context is required", nil, false)
	}
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}
	if len(primitives) > cfg.MaxInputs {
		return nil, shared.NewFailure("TRISCA_INPUT_TOO_LARGE", "primitive count exceeds configured bound", map[string]any{"max_inputs": cfg.MaxInputs}, false)
	}
	if err := shared.ValidatePrimitives(primitives); err != nil {
		return nil, err
	}

	out := make([]shared.Score, 0, len(primitives))
	for index := 0; index < len(primitives) && index < cfg.MaxInputs; index++ {
		if err := ctx.Err(); err != nil {
			return nil, shared.NewFailure("TRISCA_CONTEXT_CANCELED", err.Error(), map[string]any{"index": index}, true)
		}
		score, err := scorePrimitive(primitives[index], cfg.Theta)
		if err != nil {
			return nil, err
		}
		out = append(out, score)
	}
	return out, nil
}

func scorePrimitive(p shared.Primitive, theta Theta) (shared.Score, error) {
	weightedValue := p.Value * theta.ValueWeight
	weightedQuality := p.Quality * theta.QualityWeight
	weightedCost := p.Cost * theta.CostWeight
	weightedTime := p.Time * theta.TimeWeight
	denominator := weightedCost + weightedTime
	if denominator <= 0 {
		return shared.Score{}, shared.NewFailure("TRISCA_DENOMINATOR_INVALID", "cost plus time must be greater than zero", map[string]any{"primitive_id": p.ID}, false)
	}
	value := theta.ScoreScale * weightedValue * weightedQuality / denominator
	return shared.Score{
		PrimitiveID: p.ID,
		Value:       p.Value,
		Quality:     p.Quality,
		Cost:        p.Cost,
		Time:        p.Time,
		Influence:   p.Influence,
		Score:       value,
	}, nil
}

func normalizeConfig(cfg Config) Config {
	if cfg.MaxInputs <= 0 || cfg.MaxInputs > shared.MaxPrimitiveCount {
		cfg.MaxInputs = DefaultMaxInputs
	}
	if cfg.RuntimeCap <= 0 {
		cfg.RuntimeCap = DefaultRuntimeCap
	}
	if cfg.MemoryCapMiB <= 0 {
		cfg.MemoryCapMiB = DefaultMemoryCapMiB
	}
	if cfg.Theta.ValueWeight == 0 {
		cfg.Theta.ValueWeight = 1
	}
	if cfg.Theta.QualityWeight == 0 {
		cfg.Theta.QualityWeight = 1
	}
	if cfg.Theta.CostWeight == 0 {
		cfg.Theta.CostWeight = 1
	}
	if cfg.Theta.TimeWeight == 0 {
		cfg.Theta.TimeWeight = 1
	}
	if cfg.Theta.ScoreScale == 0 {
		cfg.Theta.ScoreScale = 1
	}
	return cfg
}

func validateConfig(cfg Config) error {
	if cfg.MaxInputs <= 0 || cfg.MaxInputs > shared.MaxPrimitiveCount {
		return shared.NewFailure("TRISCA_CONFIG_INVALID", "max inputs must be within shared primitive bound", map[string]any{"max_primitives": shared.MaxPrimitiveCount}, false)
	}
	if cfg.RuntimeCap <= 0 {
		return shared.NewFailure("TRISCA_CONFIG_INVALID", "runtime cap must be positive", nil, false)
	}
	if cfg.MemoryCapMiB <= 0 {
		return shared.NewFailure("TRISCA_CONFIG_INVALID", "memory cap must be positive", nil, false)
	}
	if cfg.Theta.ValueWeight < 0 || cfg.Theta.QualityWeight < 0 || cfg.Theta.CostWeight < 0 || cfg.Theta.TimeWeight < 0 || cfg.Theta.ScoreScale < 0 {
		return shared.NewFailure("TRISCA_THETA_INVALID", "theta weights must be non-negative", nil, false)
	}
	return nil
}
