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
			"service":    "ingestion-leader",
			"status":     "ready",
			"git_source": "commit-first",
			"cas_root":   getenv("CAS_ROOT", "/mnt/nas/cas"),
			"checked_at": time.Now().UTC(),
		})
	})
	mux.HandleFunc("/v1/foundation/event-template", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(models.Event{
			CID:        "cid-placeholder",
			Sequence:   0,
			Type:       "git.commit.normalized",
			StateHash:  "sha256-placeholder",
			GitCommit:  "HEAD",
			GitRepo:    "ark-core",
			OccurredAt: time.Now().UTC(),
			Author:     "stage-1-foundation",
			PayloadRef: "redis://cursor-plan-cache",
			Transport:  "nats.jetstream",
		})
	})

	addr := ":" + getenv("PORT", "8080")
	log.Printf("ingestion-leader foundation listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
