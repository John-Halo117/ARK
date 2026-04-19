package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	addr := envOr("HTTP_ADDR", ":8082")

	http.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("netwatch:ok"))
	})

	log.Printf("netwatch listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
