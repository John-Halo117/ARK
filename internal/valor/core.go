package valor

import (
	"context"
	"math"
	"sort"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

const (
	DefaultRuntimeCap     = 50 * time.Millisecond
	DefaultMemoryCapMiB   = 8
	DefaultMaxInputs      = shared.MaxPrimitiveCount
	DefaultSelectScoreMin = 0.66
	DefaultRejectScoreMax = 0.33
)

type Band struct {
	Name        string  `json:"name"`
	MinScore    float64 `json:"min_score"`
	MaxScore    float64 `json:"max_score"`
	MaxShare    float64 `json:"max_share"`
	Action      string  `json:"action"`
	Description string  `json:"description"`
}

type Config struct {
	Bands          []Band
	MaxInputs      int
	RuntimeCap     time.Duration
	MemoryCapMiB   int
	SelectScoreMin float64
	RejectScoreMax float64
	SortKept       bool
}

type VALORCore struct {
	cfg Config
}

func New(cfg Config) (VALORCore, error) {
	normalized := normalizeConfig(cfg)
	if err := validateConfig(normalized); err != nil {
		return VALORCore{}, err
	}
	return VALORCore{cfg: normalized}, nil
}

func (v VALORCore) Health() shared.HealthStatus {
	cfg := normalizeConfig(v.cfg)
	return shared.HealthStatus{Status: "ok", Module: "internal.valor", RuntimeCap: cfg.RuntimeCap, MemoryCapMiB: cfg.MemoryCapMiB}
}

// Run input schema: context.Context and []shared.Score from TRISCA.
// Output schema: shared.Output or shared.Failure error.
// Runtime constraint: O(n log n) when SortKept is enabled, otherwise O(n), capped by Config.MaxInputs.
// Memory assumption: O(n + bands), capped by Config.MaxInputs and shared.MaxMetricBandCount.
// Failure cases: canceled context, invalid config, invalid score, oversized input, invalid bands.
// Determinism: same scores and bands produce identical metrics and actions.
func (v VALORCore) Run(ctx context.Context, scores []shared.Score) (shared.Output, error) {
	cfg := normalizeConfig(v.cfg)
	if ctx == nil {
		return shared.Output{}, shared.NewFailure("VALOR_CONTEXT_REQUIRED", "context is required", nil, false)
	}
	if err := validateConfig(cfg); err != nil {
		return shared.Output{}, err
	}
	if len(scores) > cfg.MaxInputs {
		return shared.Output{}, shared.NewFailure("VALOR_INPUT_TOO_LARGE", "score count exceeds configured bound", map[string]any{"max_inputs": cfg.MaxInputs}, false)
	}
	if err := shared.ValidateScores(scores); err != nil {
		return shared.Output{}, err
	}
	if err := ctx.Err(); err != nil {
		return shared.Output{}, shared.NewFailure("VALOR_CONTEXT_CANCELED", err.Error(), nil, true)
	}

	bandIndexes := assignBands(scores, cfg.Bands, cfg.MaxInputs)
	metrics := computeMetrics(scores, bandIndexes, cfg.Bands, cfg.MaxInputs)
	actions, metrics, err := buildActions(ctx, scores, bandIndexes, cfg, metrics)
	if err != nil {
		return shared.Output{}, err
	}
	if cfg.SortKept {
		sortActions(actions)
	}
	return shared.Output{Status: "ok", Metrics: metrics, Actions: actions}, nil
}

func assignBands(scores []shared.Score, bands []Band, maxInputs int) []int {
	out := make([]int, 0, len(scores))
	for index := 0; index < len(scores) && index < maxInputs; index++ {
		out = append(out, findBand(scores[index].Score, bands))
	}
	return out
}

func findBand(score float64, bands []Band) int {
	for index := 0; index < len(bands) && index < shared.MaxMetricBandCount; index++ {
		if score >= bands[index].MinScore && score < bands[index].MaxScore {
			return index
		}
	}
	return len(bands) - 1
}

func computeMetrics(scores []shared.Score, bandIndexes []int, bands []Band, maxInputs int) shared.Metrics {
	total := totalInfluence(scores, maxInputs)
	distribution := make(map[string]float64, len(bands))
	for index := 0; index < len(bands) && index < shared.MaxMetricBandCount; index++ {
		distribution[bands[index].Name] = 0
	}
	for index := 0; index < len(scores) && index < len(bandIndexes) && index < maxInputs; index++ {
		if total > 0 {
			distribution[bands[bandIndexes[index]].Name] += scores[index].Influence / total
		}
	}
	return shared.Metrics{
		TotalInfluence: total,
		Distribution:   distribution,
		Entropy:        entropy(scores, maxInputs),
		Gini:           gini(scores, maxInputs),
		Zipf:           zipf(scores, maxInputs),
	}
}

func buildActions(ctx context.Context, scores []shared.Score, bandIndexes []int, cfg Config, metrics shared.Metrics) ([]shared.Action, shared.Metrics, error) {
	actions := make([]shared.Action, 0, len(scores))
	for index := 0; index < len(scores) && index < len(bandIndexes) && index < cfg.MaxInputs; index++ {
		if err := ctx.Err(); err != nil {
			return nil, metrics, shared.NewFailure("VALOR_CONTEXT_CANCELED", err.Error(), map[string]any{"index": index}, true)
		}
		action := actionForScore(scores[index], cfg)
		band := cfg.Bands[bandIndexes[index]]
		if band.MaxShare > 0 && metrics.Distribution[band.Name] > band.MaxShare {
			action.Kind = "rebalance"
			action.Reason = "band share exceeds configured max"
		}
		switch action.Kind {
		case "select":
			metrics.KeptCount++
		case "reject":
			metrics.RejectedCount++
		case "defer":
			metrics.DeferredCount++
		case "rebalance":
			metrics.RebalanceCount++
		}
		actions = append(actions, action)
	}
	return actions, metrics, nil
}

func actionForScore(score shared.Score, cfg Config) shared.Action {
	if score.Score >= cfg.SelectScoreMin {
		return shared.Action{PrimitiveID: score.PrimitiveID, Kind: "select", Reason: "score meets select threshold", Score: score.Score, Influence: score.Influence}
	}
	if score.Score <= cfg.RejectScoreMax {
		return shared.Action{PrimitiveID: score.PrimitiveID, Kind: "reject", Reason: "score falls below reject threshold", Score: score.Score, Influence: score.Influence}
	}
	return shared.Action{PrimitiveID: score.PrimitiveID, Kind: "defer", Reason: "score is inside governance review band", Score: score.Score, Influence: score.Influence}
}

func sortActions(actions []shared.Action) {
	sort.SliceStable(actions, func(left int, right int) bool {
		if actions[left].Kind != actions[right].Kind {
			return actionRank(actions[left].Kind) < actionRank(actions[right].Kind)
		}
		if actions[left].Score == actions[right].Score {
			return actions[left].PrimitiveID < actions[right].PrimitiveID
		}
		return actions[left].Score > actions[right].Score
	})
}

func actionRank(kind string) int {
	switch kind {
	case "select":
		return 0
	case "rebalance":
		return 1
	case "defer":
		return 2
	case "reject":
		return 3
	default:
		return 4
	}
}

func totalInfluence(scores []shared.Score, maxInputs int) float64 {
	total := 0.0
	for index := 0; index < len(scores) && index < maxInputs; index++ {
		total += scores[index].Influence
	}
	return total
}

func entropy(scores []shared.Score, maxInputs int) float64 {
	total := totalInfluence(scores, maxInputs)
	if total <= 0 {
		return 0
	}
	value := 0.0
	for index := 0; index < len(scores) && index < maxInputs; index++ {
		probability := scores[index].Influence / total
		if probability > 0 {
			value -= probability * math.Log(probability)
		}
	}
	if len(scores) <= 1 {
		return 0
	}
	return clamp01(value / math.Log(float64(len(scores))))
}

func gini(scores []shared.Score, maxInputs int) float64 {
	count := len(scores)
	if count == 0 {
		return 0
	}
	if count > maxInputs {
		count = maxInputs
	}
	if count <= 1 {
		return 0
	}
	values := make([]float64, 0, count)
	for index := 0; index < len(scores) && index < maxInputs; index++ {
		values = append(values, scores[index].Influence)
	}
	sort.Float64s(values)
	total := 0.0
	weighted := 0.0
	for index := 0; index < len(values) && index < maxInputs; index++ {
		total += values[index]
		weighted += float64(index+1) * values[index]
	}
	if total <= 0 {
		return 0
	}
	n := float64(len(values))
	return clamp01((2*weighted)/(n*total) - (n+1)/n)
}

func zipf(scores []shared.Score, maxInputs int) float64 {
	count := len(scores)
	if count == 0 {
		return 0
	}
	if count > maxInputs {
		count = maxInputs
	}
	if count <= 1 {
		return 0
	}
	values := make([]float64, 0, count)
	for index := 0; index < len(scores) && index < maxInputs; index++ {
		values = append(values, scores[index].Influence)
	}
	sort.Slice(values, func(left int, right int) bool {
		return values[left] > values[right]
	})
	if values[0] <= 0 {
		return 0
	}
	return clamp01(values[1] / values[0])
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
	if cfg.SelectScoreMin == 0 {
		cfg.SelectScoreMin = DefaultSelectScoreMin
	}
	if cfg.RejectScoreMax == 0 {
		cfg.RejectScoreMax = DefaultRejectScoreMax
	}
	if len(cfg.Bands) == 0 {
		cfg.Bands = defaultBands()
	}
	return cfg
}

func defaultBands() []Band {
	return []Band{
		{Name: "reject", MinScore: math.Inf(-1), MaxScore: DefaultRejectScoreMax, MaxShare: 1, Action: "reject", Description: "below governance floor"},
		{Name: "defer", MinScore: DefaultRejectScoreMax, MaxScore: DefaultSelectScoreMin, MaxShare: 0.50, Action: "defer", Description: "requires review"},
		{Name: "select", MinScore: DefaultSelectScoreMin, MaxScore: math.Inf(1), MaxShare: 0.70, Action: "select", Description: "meets governance floor"},
	}
}

func validateConfig(cfg Config) error {
	if cfg.MaxInputs <= 0 || cfg.MaxInputs > shared.MaxPrimitiveCount {
		return shared.NewFailure("VALOR_CONFIG_INVALID", "max inputs must be within shared primitive bound", map[string]any{"max_primitives": shared.MaxPrimitiveCount}, false)
	}
	if cfg.RuntimeCap <= 0 {
		return shared.NewFailure("VALOR_CONFIG_INVALID", "runtime cap must be positive", nil, false)
	}
	if cfg.MemoryCapMiB <= 0 {
		return shared.NewFailure("VALOR_CONFIG_INVALID", "memory cap must be positive", nil, false)
	}
	if cfg.RejectScoreMax >= cfg.SelectScoreMin {
		return shared.NewFailure("VALOR_THRESHOLDS_INVALID", "reject threshold must be less than select threshold", nil, false)
	}
	if len(cfg.Bands) == 0 || len(cfg.Bands) > shared.MaxMetricBandCount {
		return shared.NewFailure("VALOR_BANDS_INVALID", "band count must be within shared bound", map[string]any{"max_bands": shared.MaxMetricBandCount}, false)
	}
	for index := 0; index < len(cfg.Bands) && index < shared.MaxMetricBandCount; index++ {
		if err := validateBand(cfg.Bands[index], index); err != nil {
			return err
		}
	}
	return nil
}

func validateBand(band Band, index int) error {
	if band.Name == "" {
		return shared.NewFailure("VALOR_BAND_NAME_REQUIRED", "band name is required", map[string]any{"index": index}, false)
	}
	if band.Action != "select" && band.Action != "reject" && band.Action != "defer" && band.Action != "rebalance" {
		return shared.NewFailure("VALOR_BAND_ACTION_INVALID", "band action must be select, reject, defer, or rebalance", map[string]any{"index": index}, false)
	}
	if math.IsNaN(band.MinScore) || math.IsNaN(band.MaxScore) || math.IsNaN(band.MaxShare) {
		return shared.NewFailure("VALOR_BAND_NUMERIC_INVALID", "band numeric fields must not be NaN", map[string]any{"index": index}, false)
	}
	if band.MinScore >= band.MaxScore {
		return shared.NewFailure("VALOR_BAND_RANGE_INVALID", "band min score must be less than max score", map[string]any{"index": index}, false)
	}
	if band.MaxShare < 0 || band.MaxShare > 1 {
		return shared.NewFailure("VALOR_BAND_SHARE_INVALID", "band max share must be in [0,1]", map[string]any{"index": index}, false)
	}
	return nil
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
