package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/netwatch"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

func main() {
	addr := config.String("HTTP_ADDR", ":8082")

	kernel, err := stability.New(stability.Config{
		AlphaMax:         0.3,
		EntropyGuard:     config.Float64("ENTROPY_GUARD", 1.0),
		GMax:             config.Float64("G_MAX", 0.8),
		SigmaK:           config.Float64("SIGMA_K", 2.2),
		HysteresisLambda: config.Float64("HYSTERESIS_LAMBDA", 0.08),
		BackpressureEps:  config.Float64("BACKPRESSURE_EPS", 0.1),
		TimeDecayRate:    config.Float64("TIME_DECAY_RATE", 0.2),
		DefaultSoftWeight: stability.SoftWeights{
			WA: 0.34,
			WK: 0.33,
			WG: 0.33,
		},
	})
	if err != nil {
		log.Fatalf("kernel config invalid: %v", err)
	}

	controller, err := netwatch.New(netwatch.Config{
		AiderPath:         config.String("AIDER_PATH", "aider"),
		PfSenseHookURL:    config.String("PFSENSE_HOOK_URL", ""),
		UniFiHookURL:      config.String("UNIFI_HOOK_URL", ""),
		MaxBrowserBursts:  int(config.Float64("MAX_BROWSER_BURSTS", 3)),
		BrowserBurstReset: time.Duration(config.Float64("BROWSER_BURST_RESET_SECONDS", 60)) * time.Second,
		ExecTimeout:       time.Duration(config.Float64("NETWATCH_EXEC_TIMEOUT_SECONDS", 20)) * time.Second,
	}, kernel)
	if err != nil {
		log.Fatalf("netwatch config invalid: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("netwatch:ok"))
	})
	mux.HandleFunc("/v1/action", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		defer func() { _ = r.Body.Close() }()
		var req netwatch.ActionRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		result, err := controller.Execute(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(result)
	})
	mux.HandleFunc("/v1/s2", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		defer func() { _ = r.Body.Close() }()
		var req netwatch.ActionRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		result, err := controller.S2Baseline(r.Context(), req, "manual")
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(result)
	})

	log.Printf("netwatch listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
