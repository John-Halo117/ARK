package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/adapters/natspub"
	"github.com/John-Halo117/ARK/arkfield/internal/config"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
	"github.com/John-Halo117/ARK/arkfield/internal/wiring"
)

func main() {
	addr := config.String("HTTP_ADDR", ":8090")
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

	bridge := wiring.MQTTBridge{Publisher: publisher, Gate: kernel}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("mqtt-bridge:ok"))
	})
	mux.HandleFunc("/v1/mqtt/forward", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		defer func() { _ = r.Body.Close() }()
		var req struct {
			Topic   string `json:"topic"`
			Payload string `json:"payload"`
			Source  string `json:"source"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		event, err := bridge.Forward(wiring.MQTTMessage{Topic: req.Topic, Payload: []byte(req.Payload), Source: req.Source})
		if err != nil {
			http.Error(w, err.Error(), http.StatusConflict)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(event)
	})

	log.Printf("mqtt-bridge listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
