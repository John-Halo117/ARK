package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/adapters/gitcommit"
	"github.com/John-Halo117/ARK/arkfield/internal/adapters/natspub"
	"github.com/John-Halo117/ARK/arkfield/internal/adapters/redisstate"
	"github.com/John-Halo117/ARK/arkfield/internal/adapters/stabilitywrap"
	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/ingestion"
	"github.com/John-Halo117/ARK/arkfield/internal/projections"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

func main() {
	addr := config.String("HTTP_ADDR", ":8080")

	rdb, err := transport.NewRedisClient(config.String("REDIS_ADDR", "redis:6379"), 5*time.Second)
	if err != nil {
		log.Fatalf("redis dial failed: %v", err)
	}
	defer func() { _ = rdb.Close() }()
	if err := rdb.Ping(); err != nil {
		log.Fatalf("redis ping failed: %v", err)
	}

	natsClient, err := transport.NewNATSClient(config.String("NATS_URL", "nats://nats:4222"), 5*time.Second)
	if err != nil {
		log.Fatalf("nats connect failed: %v", err)
	}
	defer func() { _ = natsClient.Close() }()

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

	publisher := natspub.Publisher{Client: natsClient, Subject: "ark.events.cid", StreamName: "ARK_EVENTS"}
	if err := publisher.EnsureStream(); err != nil {
		log.Fatalf("jetstream ensure stream failed: %v", err)
	}

	projector := &projections.Projector{Redis: rdb, DuckDBPath: config.String("DUCKDB_PROJECTION_PATH", "/data/duckdb_projections.ndjson")}

	svc := &ingestion.Service{
		Source: gitcommit.Source{},
		Store: &redisstate.Store{
			Client:       rdb,
			DedupePrefix: "ark:statehash:",
			SequenceKey:  "ark:events:sequence",
			PendingTTL:   30 * time.Second,
		},
		Publisher: publisher,
		Stability: stabilitywrap.Evaluator{Kernel: kernel},
		Observe:   ingestion.DefaultObservation,
	}

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
			http.Error(w, err.Error(), http.StatusConflict)
			return
		}
		if !deduped {
			if err := projector.Project(*evt); err != nil {
				http.Error(w, "projection failed: "+err.Error(), http.StatusInternalServerError)
				return
			}
		}
		status := http.StatusAccepted
		if deduped {
			status = http.StatusOK
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(struct {
			Deduped bool        `json:"deduped"`
			Event   interface{} `json:"event"`
		}{Deduped: deduped, Event: evt})
	})

	mux.HandleFunc("/v1/replay", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		from, to, err := projections.ReplayRangeFromQuery(r.URL.Query().Get("from"), r.URL.Query().Get("to"))
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		events, err := projector.Replay(from, to)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(events)
	})

	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	log.Printf("ingestion-leader listening on %s", addr)
	log.Fatal(srv.ListenAndServe())
}
