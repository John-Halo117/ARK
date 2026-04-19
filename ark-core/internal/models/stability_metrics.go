package models

import "time"

// StabilityMetrics captures the state required to evaluate the Stability
// Kernel v4.2 equations, guards, and the S2 anchor recovery path.
type StabilityMetrics struct {
	Alpha                float64   `json:"alpha"`
	Target               float64   `json:"target"`
	Current              float64   `json:"current"`
	DampedUpdate         float64   `json:"damped_update"`
	TrustWeights         []float64 `json:"trust_weights,omitempty"`
	FusedValue           float64   `json:"fused_value"`
	Entropy              float64   `json:"entropy"`
	ConservationDrift    float64   `json:"conservation_drift"`
	BackpressureIn       float64   `json:"backpressure_in"`
	BackpressureOut      float64   `json:"backpressure_out"`
	BackpressureSlack    float64   `json:"backpressure_slack"`
	Curvature            float64   `json:"curvature"`
	Gradient             float64   `json:"gradient"`
	SoftGateScore        float64   `json:"soft_gate_score"`
	SoftGateAction       float64   `json:"soft_gate_action"`
	DeltaGradient        float64   `json:"delta_gradient"`
	Sigma                float64   `json:"sigma"`
	SigmaSample          float64   `json:"sigma_sample"`
	HysteresisCandidate  float64   `json:"hysteresis_candidate"`
	HysteresisCurrent    float64   `json:"hysteresis_current"`
	Lambda               float64   `json:"lambda"`
	GuardedMode          bool      `json:"guarded_mode"`
	Frozen               bool      `json:"frozen"`
	AnchorState          string    `json:"anchor_state"`
	RecoveryTheta        float64   `json:"recovery_theta"`
	RecoveryEta          float64   `json:"recovery_eta"`
	RecoveryLossGradient float64   `json:"recovery_loss_gradient"`
	EvaluatedAt          time.Time `json:"evaluated_at"`
}
