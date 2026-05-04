package stability

import (
	"math"
	"testing"
	"time"
)

func newKernel(t *testing.T) *Kernel {
	t.Helper()
	k, err := New(Config{AlphaMax: 0.3, EntropyGuard: 1, GMax: 1, SigmaK: 2.2, HysteresisLambda: 0.08, BackpressureEps: 0.1, TimeDecayRate: 0.2, DefaultSoftWeight: SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33}})
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func TestKernel_FreezeOnAlphaOverflow(t *testing.T) {
	d := newKernel(t).Evaluate(Observation{CurrentX: 0.1, TargetX: 0.8, Alpha: 0.5, Elapsed: time.Second, ProbabilityMass: []float64{0.7, 0.3}, Sigma: 1, CNew: 0.9, COld: 0.2})
	if !d.Freeze || !d.S2Activated {
		t.Fatalf("expected freeze+s2 for alpha overflow, got freeze=%v s2=%v", d.Freeze, d.S2Activated)
	}
}

func TestKernel_GuardsAndRecoveryOutputs(t *testing.T) {
	d := newKernel(t).Evaluate(Observation{CurrentX: 0.2, TargetX: 0.4, Alpha: 0.2, Elapsed: time.Second, ProbabilityMass: []float64{0.99, 0.01}, Sigma: 0.1, DeltaX: 1, CNew: 0.0, COld: 1.0, RecoveryTheta: 1, RecoveryLearningRate: 0.5, RecoveryLossGradient: 2})
	if !d.Freeze {
		t.Fatal("expected freeze due sigma+hysteresis")
	}
	if math.Abs(d.Metrics.RecoveryTheta-2.0) > 1e-9 {
		t.Fatalf("expected recovery theta 2.0, got %f", d.Metrics.RecoveryTheta)
	}
	if !d.Metrics.GuardSigmaFilter || !d.Metrics.GuardHystereticSwitch {
		t.Fatalf("expected sigma/hysteretic guards set: %+v", d.Metrics)
	}
}

func TestKernel_NoFreezePathOutputsSoftGate(t *testing.T) {
	d := newKernel(t).Evaluate(Observation{CurrentX: 0.3, TargetX: 0.35, Alpha: 0.2, Elapsed: time.Second, ProbabilityMass: []float64{0.5, 0.5}, Sigma: 1, CNew: 0.4, COld: 0.3, SignalA: 0.2, SignalK: 0.3, SignalGradC: 0.4})
	if d.Freeze {
		t.Fatalf("did not expect freeze: %+v", d)
	}
	if d.Metrics.SoftGateActivation <= 0 || d.Metrics.SoftGateActivation >= 1 {
		t.Fatalf("soft gate activation must be sigmoid output, got %f", d.Metrics.SoftGateActivation)
	}
}

func TestKernel_EntropyGuardTriggersFreezeAndS2(t *testing.T) {
	// EntropyGuard=1, probability mass is uniform over 8 buckets → entropy
	// log2(8) = 3, which exceeds the guard and must freeze + activate S2.
	k, err := New(Config{AlphaMax: 0.3, EntropyGuard: 1, GMax: 1, SigmaK: 10, HysteresisLambda: 10, BackpressureEps: 10, TimeDecayRate: 0.2, DefaultSoftWeight: SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33}})
	if err != nil {
		t.Fatal(err)
	}
	d := k.Evaluate(Observation{CurrentX: 0.3, TargetX: 0.35, Alpha: 0.1, Elapsed: time.Second, ProbabilityMass: []float64{0.125, 0.125, 0.125, 0.125, 0.125, 0.125, 0.125, 0.125}, Sigma: 1, CNew: 0.4, COld: 0.3})
	if !d.Freeze {
		t.Fatalf("expected freeze due to entropy guard, got %+v", d)
	}
	if !d.S2Activated {
		t.Fatalf("expected S2 activation when entropy guard trips, got %+v", d)
	}
}
