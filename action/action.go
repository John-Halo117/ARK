package action

import (
	"context"
	"sync"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

const (
	MaxAdapters          = 32
	MaxCompletedActions  = 128
	DefaultActionTimeout = 100 * time.Millisecond
)

type Adapter interface {
	Name() string
	Exec(context.Context, map[string]any) core.Result
	Health() core.HealthStatus
}

type Executor struct {
	mu        sync.Mutex
	adapters  map[string]Adapter
	completed map[string]core.Result
}

func NewExecutor(adapters []Adapter) (Executor, error) {
	if len(adapters) > MaxAdapters {
		return Executor{}, core.NewFailure("ACTION_ADAPTERS_TOO_LARGE", "adapter table exceeds bounded count", map[string]any{"max_adapters": MaxAdapters}, false)
	}
	table := make(map[string]Adapter, len(adapters))
	for i := 0; i < len(adapters) && i < MaxAdapters; i++ {
		adapter := adapters[i]
		if adapter == nil || adapter.Name() == "" {
			return Executor{}, core.NewFailure("ACTION_ADAPTER_INVALID", "adapter must expose a name", map[string]any{"index": i}, false)
		}
		table[adapter.Name()] = adapter
	}
	return Executor{adapters: table, completed: map[string]core.Result{}}, nil
}

func (e Executor) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "action.executor", RuntimeCap: DefaultActionTimeout, MemoryCapMiB: 4}
}

// Exec is the thin idempotent action boundary.
func (e *Executor) Exec(ctx context.Context, intent core.Intent) core.Result {
	if intent.Noop || intent.Action == "noop" {
		return core.Result{ID: intent.ID, Status: "ok", Action: "noop", Output: map[string]any{"noop": true}}
	}
	e.mu.Lock()
	if cached, ok := e.completed[intent.ID]; ok {
		e.mu.Unlock()
		return cached
	}
	if len(e.completed) >= MaxCompletedActions {
		e.mu.Unlock()
		failure := core.NewFailure("ACTION_CACHE_FULL", "completed action cache reached bounded capacity", map[string]any{"max_completed": MaxCompletedActions}, true)
		return core.Result{ID: intent.ID, Status: "error", Action: intent.Action, Failure: &failure}
	}
	adapter, ok := e.adapters[intent.Action]
	if !ok {
		e.mu.Unlock()
		failure := core.NewFailure("ACTION_ADAPTER_MISSING", "no adapter registered for intent action", map[string]any{"action": intent.Action}, false)
		return core.Result{ID: intent.ID, Status: "error", Action: intent.Action, Failure: &failure}
	}

	result := adapter.Exec(ctx, intent.Params)
	result.ID = intent.ID
	result.Action = intent.Action
	if result.Status == "" {
		result.Status = "ok"
	}
	e.completed[intent.ID] = result
	e.mu.Unlock()
	return result
}

type MemoryAdapter struct {
	name string
}

func NewMemoryAdapter(name string) MemoryAdapter {
	return MemoryAdapter{name: name}
}

func (a MemoryAdapter) Name() string {
	return a.name
}

func (a MemoryAdapter) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "action.adapter." + a.name, RuntimeCap: DefaultActionTimeout, MemoryCapMiB: 2}
}

func (a MemoryAdapter) Exec(ctx context.Context, params map[string]any) core.Result {
	select {
	case <-ctx.Done():
		failure := core.NewFailure("ACTION_TIMEOUT", "action context expired", map[string]any{"adapter": a.name}, true)
		return core.Result{Status: "error", Action: a.name, Failure: &failure}
	default:
	}
	output := make(map[string]any, len(params)+1)
	for key, value := range params {
		if len(output) >= core.MaxPayloadKeys {
			failure := core.NewFailure("ACTION_PARAMS_TOO_LARGE", "action params exceed bounded key count", nil, false)
			return core.Result{Status: "error", Action: a.name, Failure: &failure}
		}
		output[key] = value
	}
	output["adapter"] = a.name
	return core.Result{Status: "ok", Action: a.name, Output: output}
}
