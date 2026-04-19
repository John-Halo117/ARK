package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/ingestion"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

func main() {
	addr := envOr("HTTP_ADDR", ":8080")

	rdb, err := transport.NewRedisClient(envOr("REDIS_ADDR", "redis:6379"), 5*time.Second)
	if err != nil {
		log.Fatalf("redis dial failed: %v", err)
	}
	defer func() { _ = rdb.Close() }()
	if err := rdb.Ping(); err != nil {
		log.Fatalf("redis ping failed: %v", err)
	}

	nc, err := transport.NewNATSClient(envOr("NATS_URL", "nats://nats:4222"), 5*time.Second)
	if err != nil {
		log.Fatalf("nats connect failed: %v", err)
	}
	defer func() { _ = nc.Close() }()

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
		log.Fatalf("kernel config invalid: %v", err)
	}

	svc := &ingestion.Service{Redis: rdb, NATS: nc, Kernel: kernel}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ingestion-leader:ok"))
	})
	mux.HandleFunc("/v1/ingest/git-commit", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		defer func() { _ = r.Body.Close() }()

		var req ingestion.IngestRequest
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}

		evt, deduped, err := svc.IngestGitCommit(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		status := http.StatusAccepted
		if deduped {
			status = http.StatusOK
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(struct {
			Deduped bool `json:"deduped"`
			Event   any  `json:"event"`
		}{Deduped: deduped, Event: evt})
	})

	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	log.Printf("ingestion-leader listening on %s", addr)
	log.Fatal(srv.ListenAndServe())
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
