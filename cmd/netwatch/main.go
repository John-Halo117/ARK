package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os/exec"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/crypto"
	"github.com/John-Halo117/ARK/arkfield/internal/runtime"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

func main() {
	cfg := config.LoadRuntimeConfig(":8082")
	lastAuditHash := ""

	priv, err := crypto.LoadPrivateKeyFromSeedHex(cfg.SigningSeedHex)
	if err != nil {
		log.Fatalf("missing signing key: %v", err)
	}

	toggles := runtime.NewToggleStore(map[string]bool{
		"safe_mode": false,
		"autonomy":  true,
		"external":  false,
	})

	kernel, err := stability.New(stability.Config{
		AlphaMax:          0.3,
		EntropyGuard:      1.0,
		GMax:              cfg.GMax,
		SigmaK:            cfg.SigmaK,
		HysteresisLambda:  cfg.HysteresisLambda,
		BackpressureEps:   cfg.BackpressureEps,
		TimeDecayRate:     cfg.TimeDecayRate,
		DefaultSoftWeight: stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33},
	})
	if err != nil {
		log.Fatalf("stability kernel config: %v", err)
	}

	mux := http.NewServeMux()
	mux.Handle("/toggles", runtime.WithTrace(runtime.RequireMethod("GET", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		runtime.WriteJSON(w, toggles.Snapshot())
	}))))

	mux.Handle("/toggles/set", runtime.WithTrace(runtime.RequireAuth(cfg.APIToken, runtime.RequireMethod("POST", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name   string `json:"name"`
			Enable bool   `json:"enable"`
			Reason string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		runtime.WriteJSON(w, toggles.Set(req.Name, req.Enable, req.Reason))
	})))))

	mux.Handle("/verify", runtime.WithTrace(runtime.RequireMethod("POST", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var env crypto.Envelope
		if err := json.NewDecoder(r.Body).Decode(&env); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		runtime.WriteJSON(w, map[string]bool{"valid": crypto.VerifyEnvelope(env)})
	}))))

	mux.Handle("/audit/root", runtime.WithTrace(runtime.RequireMethod("GET", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		runtime.WriteJSON(w, map[string]string{"last": lastAuditHash})
	}))))

	mux.Handle("/gate", runtime.WithTrace(runtime.RequireAuth(cfg.APIToken, runtime.RequireMethod("POST", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var obs stability.Observation
		if err := json.NewDecoder(r.Body).Decode(&obs); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if obs.Elapsed == 0 {
			obs.Elapsed = time.Second
		}

		decision := kernel.Evaluate(obs)
		payload, err := json.Marshal(decision)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		env, err := crypto.SignEnvelope(priv, payload)
		if err != nil {
			autoRecover()
			w.WriteHeader(http.StatusInternalServerError)
			return
		}

		entry, err := crypto.AppendAudit(cfg.AuditLogPath, env.CID, lastAuditHash)
		if err != nil {
			autoRecover()
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		lastAuditHash = entry.Hash

		if decision.Freeze {
			autoRecover()
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}

		runtime.WriteJSON(w, env)
	})))))

	mux.Handle("/health", runtime.WithTrace(runtime.RequireMethod("GET", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("netwatch:ok"))
	}))))

	log.Printf("netwatch listening on %s", cfg.HTTPAddr)
	log.Fatal(http.ListenAndServe(cfg.HTTPAddr, mux))
}

func autoRecover() {
	_ = exec.Command("bash", "scripts/ci/recover.sh").Start()
}
