package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/ingestion"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

func main() {
	cfg := config.LoadRuntimeConfig(":8080")

	rdb, err := transport.NewRedisClient(cfg.RedisAddr, 5*time.Second)
	if err != nil {
		log.Fatalf("redis dial failed: %v", err)
	}
	defer rdb.Close()

	nc, err := transport.NewNATSClient(cfg.NATSURL, 5*time.Second)
	if err != nil {
		log.Fatalf("nats connect failed: %v", err)
	}
	defer nc.Close()

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
		log.Fatalf("kernel config invalid: %v", err)
	}

	svc := &ingestion.Service{Redis: rdb, NATS: nc, Kernel: kernel}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ingestion-leader:ok"))
	})

	mux.HandleFunc("/v1/ingest/git-commit", func(w http.ResponseWriter, r *http.Request) {
		var req ingestion.IngestRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}

		evt, _, err := svc.IngestGitCommit(r.Context(), req)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		json.NewEncoder(w).Encode(evt)
	})

	log.Printf("ingestion-leader listening on %s", cfg.HTTPAddr)
	log.Fatal(http.ListenAndServe(cfg.HTTPAddr, mux))
}
