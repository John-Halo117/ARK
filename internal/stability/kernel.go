package stability

import (
	"errors"
	"math"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
)

type Config struct {
	AlphaMax          float64
	EntropyGuard      float64
	GMax              float64
	SigmaK            float64
	HysteresisLambda  float64
	BackpressureEps   float64
	TimeDecayRate     float64
	DefaultSoftWeight SoftWeights
}

type SoftWeights struct {
	WA float64 `json:"w_a"`
	WK float64 `json:"w_k"`
	WG float64 `json:"w_g"`
}

type Observation struct {
	CurrentX             float64         `json:"current_x"`
	TargetX              float64         `json:"target_x"`
	Alpha                float64         `json:"alpha"`
	Elapsed              time.Duration   `json:"elapsed"`
	TrustSources         []TrustSample   `json:"trust_sources"`
	ProbabilityMass      []float64       `json:"probability_mass"`
	VelocityDivergence   float64         `json:"velocity_divergence"`
	RateIn               float64         `json:"rate_in"`
	RateOut              float64         `json:"rate_out"`
	BackpressureEpsilon  float64         `json:"backpressure_epsilon"`
	CurvatureCenter      float64         `json:"curvature_center"`
	CurvatureNeighbors   []CurvatureNode `json:"curvature_neighbors"`
	SignalA              float64         `json:"signal_a"`
	SignalK              float64         `json:"signal_k"`
	SignalGradC          float64         `json:"signal_grad_c"`
	SoftWeights          SoftWeights     `json:"soft_weights"`
	DeltaG               float64         `json:"delta_g"`
	DeltaX               float64         `json:"delta_x"`
	Sigma                float64         `json:"sigma"`
	CNew                 float64         `json:"c_new"`
	COld                 float64         `json:"c_old"`
	RecoveryTheta        float64         `json:"recovery_theta"`
	RecoveryLearningRate float64         `json:"recovery_learning_rate"`
	RecoveryLossGradient float64         `json:"recovery_loss_gradient"`
}

type TrustSample struct {
	Weight float64 `json:"weight"`
	Value  float64 `json:"value"`
}

type CurvatureNode struct {
	C float64 `json:"c"`
	W float64 `json:"w"`
}

type Decision struct {
	NextX       float64                 `json:"next_x"`
	Metrics     models.StabilityMetrics `json:"metrics"`
	Freeze      bool                    `json:"freeze"`
	Reason      string                  `json:"reason,omitempty"`
	S2Activated bool                    `json:"s2_activated"`
}

type Kernel struct {
	cfg Config
}

func New(cfg Config) (*Kernel, error) {
	if cfg.AlphaMax <= 0 || cfg.AlphaMax > 0.3 {
		return nil, errors.New("alpha_max must satisfy 0 < alpha_max <= 0.3")
	}
	if cfg.SigmaK <= 0 {
		return nil, errors.New("sigma_k must be > 0")
	}
	if cfg.HysteresisLambda <= 0 {
		return nil, errors.New("hysteresis_lambda must be > 0")
	}
	if cfg.TimeDecayRate < 0 {
		return nil, errors.New("time_decay_rate must be >= 0")
	}
	if cfg.EntropyGuard <= 0 {
		return nil, errors.New("entropy_guard must be > 0")
	}
	return &Kernel{cfg: cfg}, nil
}

func (k *Kernel) Evaluate(o Observation) Decision {
	if o.BackpressureEpsilon == 0 {
		o.BackpressureEpsilon = k.cfg.BackpressureEps
	}
	weights := o.SoftWeights
	if weights == (SoftWeights{}) {
		weights = k.cfg.DefaultSoftWeight
	}

	wT := math.Exp(-k.cfg.TimeDecayRate * o.Elapsed.Seconds())
	alpha := clamp(o.Alpha, 0, k.cfg.AlphaMax)
	nextX := o.CurrentX + alpha*(o.TargetX-o.CurrentX)*wT

	trustValue := trustWeightedFusion(o.TrustSources)
	entropyValue := entropy(o.ProbabilityMass)
	divergence := o.VelocityDivergence
	backpressureViolation := o.RateIn > o.RateOut+o.BackpressureEpsilon
	curvatureValue := curvature(o.CurvatureCenter, o.CurvatureNeighbors)
	score := weights.WA*o.SignalA + weights.WK*o.SignalK + weights.WG*o.SignalGradC
	activation := sigmoid(score)

	guardFreeze := math.Abs(o.DeltaG) > k.cfg.GMax || divergence != 0 || backpressureViolation
	guardSigma := math.Abs(o.DeltaX) > k.cfg.SigmaK*math.Max(o.Sigma, 1e-9)
	guardHysteretic := o.CNew+k.cfg.HysteresisLambda < o.COld
	guardBoundedReaction := !(o.Alpha > 0 && o.Alpha < 1)

	recoveryTheta := o.RecoveryTheta + o.RecoveryLearningRate*o.RecoveryLossGradient

	s2 := guardFreeze || entropyValue > k.cfg.EntropyGuard
	reason := ""
	if guardFreeze {
		reason = "hard_freeze"
	} else if entropyValue > k.cfg.EntropyGuard {
		reason = "entropy_guard"
	}

	metrics := models.StabilityMetrics{
		Alpha:                 alpha,
		TimeDecayWeight:       wT,
		TrustWeightedValue:    trustValue,
		Entropy:               entropyValue,
		Divergence:            divergence,
		BackpressureIn:        o.RateIn,
		BackpressureOut:       o.RateOut,
		BackpressureEpsilon:   o.BackpressureEpsilon,
		Curvature:             curvatureValue,
		SoftGateScore:         score,
		SoftGateActivation:    activation,
		DeltaG:                o.DeltaG,
		SigmaDeltaX:           o.DeltaX,
		HysteresisCNew:        o.CNew,
		HysteresisCOld:        o.COld,
		HysteresisLambda:      k.cfg.HysteresisLambda,
		RecoveryTheta:         recoveryTheta,
		RecoveryLearningRate:  o.RecoveryLearningRate,
		RecoveryLossGradient:  o.RecoveryLossGradient,
		GuardFreeze:           guardFreeze,
		GuardSigmaFilter:      guardSigma,
		GuardHystereticSwitch: guardHysteretic,
		GuardBoundedReaction:  guardBoundedReaction,
		S2AnchorActive:        s2,
		LastUpdated:           time.Now().UTC(),
	}

	return Decision{
		NextX:       nextX,
		Metrics:     metrics,
		Freeze:      guardFreeze || guardSigma || guardHysteretic || guardBoundedReaction,
		Reason:      reason,
		S2Activated: s2,
	}
}

func trustWeightedFusion(samples []TrustSample) float64 {
	if len(samples) == 0 {
		return 0
	}
	var sumW, total float64
	for _, s := range samples {
		if s.Weight < 0 {
			continue
		}
		sumW += s.Weight
		total += s.Weight * s.Value
	}
	if sumW == 0 {
		return 0
	}
	return total / sumW
}

func entropy(probs []float64) float64 {
	var h float64
	for _, p := range probs {
		if p <= 0 {
			continue
		}
		h -= p * math.Log(p)
	}
	return h
}

func curvature(center float64, neighbors []CurvatureNode) float64 {
	var k float64
	for _, n := range neighbors {
		k += (n.C - center) * n.W
	}
	return k
}

func sigmoid(v float64) float64 {
	return 1.0 / (1.0 + math.Exp(-v))
}

func clamp(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
