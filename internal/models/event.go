package models

import "time"

// Event is the canonical object emitted by the Ingestion Leader.
// It is derived from a Git commit diff and wrapped with sequence metadata.
type Event struct {
	CID         string            `json:"cid"`
	Sequence    uint64            `json:"sequence"`
	StateHash   string            `json:"state_hash"`
	ParentCID   string            `json:"parent_cid,omitempty"`
	Repo        string            `json:"repo"`
	CommitSHA   string            `json:"commit_sha"`
	Author      string            `json:"author"`
	OccurredAt  time.Time         `json:"occurred_at"`
	Canonical   []byte            `json:"canonical"`
	Attributes  map[string]string `json:"attributes,omitempty"`
	StabilityOK bool              `json:"stability_ok"`
}

// CIDObject stores immutable event bytes and integrity metadata for CAS usage.
type CIDObject struct {
	CID         string            `json:"cid"`
	Codec       string            `json:"codec"`
	Compression string            `json:"compression"`
	SizeBytes   int64             `json:"size_bytes"`
	SHA256      string            `json:"sha256"`
	CreatedAt   time.Time         `json:"created_at"`
	Path        string            `json:"path"`
	Headers     map[string]string `json:"headers,omitempty"`
}

// StabilityMetrics carries kernel equation outputs + guard state.
// This model is passed between Ingestion Leader, Stability Kernel, and NetWatch.
type StabilityMetrics struct {
	Alpha                    float64   `json:"alpha"`
	TimeDecayWeight          float64   `json:"time_decay_weight"`
	TrustWeightedValue       float64   `json:"trust_weighted_value"`
	Entropy                  float64   `json:"entropy"`
	Divergence               float64   `json:"divergence"`
	BackpressureIn           float64   `json:"backpressure_in"`
	BackpressureOut          float64   `json:"backpressure_out"`
	BackpressureEpsilon      float64   `json:"backpressure_epsilon"`
	Curvature                float64   `json:"curvature"`
	SoftGateScore            float64   `json:"soft_gate_score"`
	SoftGateActivation       float64   `json:"soft_gate_activation"`
	DeltaG                   float64   `json:"delta_g"`
	SigmaDeltaX              float64   `json:"sigma_delta_x"`
	HysteresisCNew           float64   `json:"hysteresis_c_new"`
	HysteresisCOld           float64   `json:"hysteresis_c_old"`
	HysteresisLambda         float64   `json:"hysteresis_lambda"`
	RecoveryTheta            float64   `json:"recovery_theta"`
	RecoveryLearningRate     float64   `json:"recovery_learning_rate"`
	RecoveryLossGradient     float64   `json:"recovery_loss_gradient"`
	GuardFreeze              bool      `json:"guard_freeze"`
	GuardSigmaFilter         bool      `json:"guard_sigma_filter"`
	GuardHystereticSwitch    bool      `json:"guard_hysteretic_switch"`
	GuardBoundedReaction     bool      `json:"guard_bounded_reaction"`
	S2AnchorActive           bool      `json:"s2_anchor_active"`
	LastUpdated              time.Time `json:"last_updated"`
}
