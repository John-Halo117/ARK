package api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
	"github.com/John-Halo117/ARK/arkfield/gsb"
)

const (
	MaxRequestBytes = 1 << 20
	APITimeout      = 500 * time.Millisecond
)

type Server struct {
	Interpreter core.Interpreter
	Bus         gsb.Bus
}

func (s Server) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "api.server", RuntimeCap: APITimeout, MemoryCapMiB: 16}
}

func (s Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/ingest", s.handleIngest)
	mux.HandleFunc("/gsb", s.handleGSB)
	mux.HandleFunc("/trisca", s.handleTRISCA)
	mux.HandleFunc("/policy", s.handlePolicy)
	mux.HandleFunc("/action", s.handleAction)
	mux.HandleFunc("/meta", s.handleMeta)
	return mux
}

func (s Server) handleIngest(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var event core.Event
	if !decodeJSON(w, r, &event) {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), APITimeout)
	defer cancel()
	writeJSON(w, s.Interpreter.HandleEvent(ctx, event), http.StatusOK)
}

func (s Server) handleGSB(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req struct {
		Topic   string `json:"topic"`
		Payload string `json:"payload"`
	}
	if !decodeJSON(w, r, &req) {
		return
	}
	if s.Bus == nil {
		writeFailure(w, core.NewFailure("GSB_UNAVAILABLE", "gsb bus is not configured", nil, true), http.StatusServiceUnavailable)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), APITimeout)
	defer cancel()
	if err := s.Bus.Publish(ctx, req.Topic, []byte(req.Payload)); err != nil {
		writeFailure(w, failureFromError(err), http.StatusBadRequest)
		return
	}
	writeJSON(w, map[string]any{"status": "ok"}, http.StatusOK)
}

func (s Server) handleTRISCA(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var resolved core.ResolvedEvent
	if !decodeJSON(w, r, &resolved) {
		return
	}
	out, err := s.Interpreter.Runtime.TRISCA.Compute(resolved)
	if err != nil {
		writeFailure(w, failureFromError(err), http.StatusBadRequest)
		return
	}
	writeJSON(w, out, http.StatusOK)
}

func (s Server) handlePolicy(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req struct {
		Resolved core.ResolvedEvent `json:"resolved"`
		TRISCA   core.TRISCAOutput  `json:"trisca"`
	}
	if !decodeJSON(w, r, &req) {
		return
	}
	intent, err := s.Interpreter.Runtime.Policy.Evaluate(req.Resolved, req.TRISCA)
	if err != nil {
		writeFailure(w, failureFromError(err), http.StatusBadRequest)
		return
	}
	writeJSON(w, intent, http.StatusOK)
}

func (s Server) handleAction(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var intent core.Intent
	if !decodeJSON(w, r, &intent) {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), APITimeout)
	defer cancel()
	writeJSON(w, s.Interpreter.Runtime.Action.Exec(ctx, intent), http.StatusOK)
}

func (s Server) handleMeta(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req struct {
		Logs   []core.StepLog `json:"logs"`
		Result core.Result    `json:"result"`
	}
	if !decodeJSON(w, r, &req) {
		return
	}
	deltas, err := s.Interpreter.Runtime.Meta.Consume(req.Logs, req.Result)
	if err != nil {
		writeFailure(w, failureFromError(err), http.StatusBadRequest)
		return
	}
	if err := s.Interpreter.Runtime.Meta.Apply(deltas); err != nil {
		writeFailure(w, failureFromError(err), http.StatusBadRequest)
		return
	}
	writeJSON(w, deltas, http.StatusOK)
}

func requireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method != method {
		writeFailure(w, core.NewFailure("METHOD_NOT_ALLOWED", "method is not allowed", map[string]any{"method": r.Method}, false), http.StatusMethodNotAllowed)
		return false
	}
	return true
}

func decodeJSON(w http.ResponseWriter, r *http.Request, target any) bool {
	reader := io.LimitReader(r.Body, MaxRequestBytes)
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		writeFailure(w, core.NewFailure("INVALID_JSON", "request body must be valid bounded json", map[string]any{"error": err.Error()}, false), http.StatusBadRequest)
		return false
	}
	return true
}

func writeJSON(w http.ResponseWriter, value any, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeFailure(w http.ResponseWriter, failure core.Failure, status int) {
	writeJSON(w, failure, status)
}

func failureFromError(err error) core.Failure {
	if failure, ok := err.(core.Failure); ok {
		return failure
	}
	return core.NewFailure("UNEXPECTED_ERROR", err.Error(), nil, true)
}
