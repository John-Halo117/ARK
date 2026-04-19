package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/John-Halo117/ARK/ark-core/internal/models"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"service":    "stability-kernel",
			"status":     "ready",
			"anchor":     "S2",
			"checked_at": time.Now().UTC(),
		})
	})
	mux.HandleFunc("/v1/foundation/metrics-template", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(models.StabilityMetrics{
			Alpha:             0.3,
			Entropy:           0,
			ConservationDrift: 0,
			BackpressureIn:    0,
			BackpressureOut:   0,
			BackpressureSlack: 0,
			SoftGateScore:     0,
			SoftGateAction:    0.5,
			AnchorState:       "S2",
			GuardedMode:       false,
			Frozen:            false,
			RecoveryTheta:     0,
			EvaluatedAt:       time.Now().UTC(),
		})
	})

	addr := ":" + getenv("PORT", "8080")
	log.Printf("stability-kernel foundation listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
