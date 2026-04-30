package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

func main() {
	cfg := config.LoadRuntimeConfig(":8081")

	kernel, err := stability.New(stability.Config{
		AlphaMax:         0.3,
		EntropyGuard:     1.0,
		GMax:             cfg.GMax,
		SigmaK:           cfg.SigmaK,
		HysteresisLambda: cfg.HysteresisLambda,
		BackpressureEps:  cfg.BackpressureEps,
		TimeDecayRate:    cfg.TimeDecayRate,
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
		w.Write([]byte("stability-kernel:ok"))
	})

	mux.HandleFunc("/config", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(cfg)
	})

	mux.HandleFunc("/v1/evaluate", func(w http.ResponseWriter, r *http.Request) {
		var obs stability.Observation
		if err := json.NewDecoder(r.Body).Decode(&obs); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		decision := kernel.Evaluate(obs)
		json.NewEncoder(w).Encode(decision)
	})

	log.Printf("stability-kernel listening on %s", cfg.HTTPAddr)
	log.Fatal(http.ListenAndServe(cfg.HTTPAddr, mux))
}
