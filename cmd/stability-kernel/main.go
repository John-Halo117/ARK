package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type evaluateRequest struct {
	CurrentX             float64                   `json:"current_x"`
	TargetX              float64                   `json:"target_x"`
	Alpha                float64                   `json:"alpha"`
	ElapsedMilliseconds  int64                     `json:"elapsed_milliseconds"`
	TrustSources         []stability.TrustSample   `json:"trust_sources"`
	ProbabilityMass      []float64                 `json:"probability_mass"`
	VelocityDivergence   float64                   `json:"velocity_divergence"`
	RateIn               float64                   `json:"rate_in"`
	RateOut              float64                   `json:"rate_out"`
	BackpressureEpsilon  float64                   `json:"backpressure_epsilon"`
	CurvatureCenter      float64                   `json:"curvature_center"`
	CurvatureNeighbors   []stability.CurvatureNode `json:"curvature_neighbors"`
	SignalA              float64                   `json:"signal_a"`
	SignalK              float64                   `json:"signal_k"`
	SignalGradC          float64                   `json:"signal_grad_c"`
	SoftWeights          stability.SoftWeights     `json:"soft_weights"`
	DeltaG               float64                   `json:"delta_g"`
	DeltaX               float64                   `json:"delta_x"`
	Sigma                float64                   `json:"sigma"`
	CNew                 float64                   `json:"c_new"`
	COld                 float64                   `json:"c_old"`
	RecoveryTheta        float64                   `json:"recovery_theta"`
	RecoveryLearningRate float64                   `json:"recovery_learning_rate"`
	RecoveryLossGradient float64                   `json:"recovery_loss_gradient"`
}

func main() {
	addr := envOr("HTTP_ADDR", ":8081")
	kernel, err := stability.New(stability.Config{
		AlphaMax:         0.3,
		EntropyGuard:     1.0,
		GMax:             envOrFloat("G_MAX", 0.8),
		SigmaK:           envOrFloat("SIGMA_K", 2.2),
		HysteresisLambda: envOrFloat("HYSTERESIS_LAMBDA", 0.08),
		BackpressureEps:  envOrFloat("BACKPRESSURE_EPS", 0.1),
		TimeDecayRate:    envOrFloat("TIME_DECAY_RATE", 0.2),
		DefaultSoftWeight: stability.SoftWeights{
			WA: 0.34, WK: 0.33, WG: 0.33,
		},
	})
	if err != nil {
		log.Fatalf("stability kernel config: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("stability-kernel:ok"))
	})
	mux.HandleFunc("/v1/evaluate", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		defer func() { _ = r.Body.Close() }()

		var req evaluateRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}

		decision := kernel.Evaluate(stability.Observation{
			CurrentX:             req.CurrentX,
			TargetX:              req.TargetX,
			Alpha:                req.Alpha,
			Elapsed:              time.Duration(req.ElapsedMilliseconds) * time.Millisecond,
			TrustSources:         req.TrustSources,
			ProbabilityMass:      req.ProbabilityMass,
			VelocityDivergence:   req.VelocityDivergence,
			RateIn:               req.RateIn,
			RateOut:              req.RateOut,
			BackpressureEpsilon:  req.BackpressureEpsilon,
			CurvatureCenter:      req.CurvatureCenter,
			CurvatureNeighbors:   req.CurvatureNeighbors,
			SignalA:              req.SignalA,
			SignalK:              req.SignalK,
			SignalGradC:          req.SignalGradC,
			SoftWeights:          req.SoftWeights,
			DeltaG:               req.DeltaG,
			DeltaX:               req.DeltaX,
			Sigma:                req.Sigma,
			CNew:                 req.CNew,
			COld:                 req.COld,
			RecoveryTheta:        req.RecoveryTheta,
			RecoveryLearningRate: req.RecoveryLearningRate,
			RecoveryLossGradient: req.RecoveryLossGradient,
		})

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(decision)
	})

	log.Printf("stability-kernel listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envOrFloat(key string, fallback float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return fallback
	}
	return f
}
