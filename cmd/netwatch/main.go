package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/crypto"
	"github.com/John-Halo117/ARK/arkfield/internal/runtime"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

var lastAuditHash string

func main() {
	cfg := config.LoadRuntimeConfig(":8082")

	priv, err := crypto.LoadPrivateKeyFromSeedHex(cfg.SigningSeedHex)
	if err != nil {
		log.Fatalf("missing signing key: %v", err)
	}

	kernel, _ := stability.New(stability.Config{
		AlphaMax: 0.3,
		EntropyGuard: 1.0,
		GMax: cfg.GMax,
		SigmaK: cfg.SigmaK,
		HysteresisLambda: cfg.HysteresisLambda,
		BackpressureEps: cfg.BackpressureEps,
		TimeDecayRate: cfg.TimeDecayRate,
		DefaultSoftWeight: stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33},
	})

	mux := http.NewServeMux()

	mux.Handle("/verify", runtime.WithTrace(runtime.RequireMethod("POST", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var env crypto.Envelope
		json.NewDecoder(r.Body).Decode(&env)
		ok := crypto.VerifyEnvelope(env)
		json.NewEncoder(w).Encode(map[string]bool{"valid": ok})
	}))))

	mux.Handle("/audit/root", runtime.WithTrace(runtime.RequireMethod("GET", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		json.NewEncoder(w).Encode(map[string]string{"last": lastAuditHash})
	}))))

	mux.Handle("/gate", runtime.WithTrace(runtime.RequireAuth(cfg.APIToken, runtime.RequireMethod("POST", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var obs stability.Observation
		_ = json.NewDecoder(r.Body).Decode(&obs)
		if obs.Elapsed == 0 {
			obs.Elapsed = time.Second
		}

		decision := kernel.Evaluate(obs)
		payload, _ := json.Marshal(decision)

		env, _ := crypto.SignEnvelope(priv, payload)
		entry, _ := crypto.AppendAudit(cfg.AuditLogPath, env.CID, lastAuditHash)
		lastAuditHash = entry.Hash

		if decision.Freeze {
			w.WriteHeader(http.StatusServiceUnavailable)
		}

		json.NewEncoder(w).Encode(env)
	}))))

	mux.Handle("/health", runtime.WithTrace(runtime.RequireMethod("GET", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("netwatch:ok"))
	}))))

	log.Printf("netwatch listening on %s", cfg.HTTPAddr)
	log.Fatal(http.ListenAndServe(cfg.HTTPAddr, mux))
}
