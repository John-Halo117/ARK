package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"service":          "netwatch",
			"status":           "ready",
			"mutation_backend": "aider",
			"planning_backend": "cursor+redis-cache",
			"checked_at":       time.Now().UTC(),
		})
	})

	addr := ":" + getenv("PORT", "8080")
	log.Printf("netwatch foundation listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
