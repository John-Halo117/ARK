package shared

import (
	"fmt"
	"time"
)

const (
	MaxHashBytes       = 128
	MaxPathBytes       = 4096
	MaxPrimitiveCount  = 256
	MaxPrimitiveID     = 128
	MaxSemanticLabels  = 16
	MaxSemanticLabel   = 64
	MaxMetricBandCount = 16
	MaxEmbeddingDims   = 4096
	MaxIndexMatches    = 32
	MaxMatchID         = 128
)

// Failure is the standard structured error object for invariant subsystems.
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

// HealthStatus exposes bounded module readiness without process-global state.
type HealthStatus struct {
	Status       string        `json:"status"`
	Module       string        `json:"module"`
	RuntimeCap   time.Duration `json:"runtime_cap"`
	MemoryCapMiB int           `json:"memory_cap_mib"`
}

// Primitive is the shared semantic/scoring atom emitted by MIDAS and consumed by TRISCA.
type Primitive struct {
	ID        string            `json:"id"`
	Value     float64           `json:"value"`
	Quality   float64           `json:"quality"`
	Cost      float64           `json:"cost"`
	Time      float64           `json:"time"`
	Influence float64           `json:"influence"`
	Labels    []string          `json:"labels,omitempty"`
	Metadata  map[string]string `json:"metadata,omitempty"`
}

// Score is the deterministic TRISCA score for one Primitive.
type Score struct {
	PrimitiveID string  `json:"primitive_id"`
	Value       float64 `json:"value"`
	Quality     float64 `json:"quality"`
	Cost        float64 `json:"cost"`
	Time        float64 `json:"time"`
	Influence   float64 `json:"influence"`
	Score       float64 `json:"score"`
}

// Metrics describes the VALOR distribution view over scored primitives.
type Metrics struct {
	TotalInfluence float64            `json:"total_influence"`
	Distribution   map[string]float64 `json:"distribution"`
	Entropy        float64            `json:"entropy"`
	Gini           float64            `json:"gini"`
	Zipf           float64            `json:"zipf"`
	KeptCount      int                `json:"kept_count"`
	RejectedCount  int                `json:"rejected_count"`
	DeferredCount  int                `json:"deferred_count"`
	RebalanceCount int                `json:"rebalance_count"`
}

// Band describes one VALOR governance constraint band.
type Band struct {
	Name        string  `json:"name"`
	MinScore    float64 `json:"min_score"`
	MaxScore    float64 `json:"max_score"`
	MaxShare    float64 `json:"max_share"`
	Action      string  `json:"action"`
	Description string  `json:"description"`
}

// Action is the governance action emitted by VALOR.
type Action struct {
	PrimitiveID string  `json:"primitive_id"`
	Kind        string  `json:"kind"`
	Reason      string  `json:"reason"`
	Score       float64 `json:"score"`
	Influence   float64 `json:"influence"`
}

// Output is the complete VALOR governance result.
type Output struct {
	Status  string   `json:"status"`
	Metrics Metrics  `json:"metrics"`
	Actions []Action `json:"actions"`
	Failure *Failure `json:"failure,omitempty"`
}

// Sidecar is the MIDAS semantic sidecar. The canonical blob is referenced, never mutated.
type Sidecar struct {
	Hash       string      `json:"hash"`
	Path       string      `json:"path"`
	Primitives []Primitive `json:"primitives"`
	Embedding  []float64   `json:"embedding,omitempty"`
	Matches    []Match     `json:"matches,omitempty"`
}

// Match captures bounded semantic index neighbors used during enrichment.
type Match struct {
	ID         string  `json:"id"`
	Similarity float64 `json:"similarity"`
}
