package core

import (
	"context"
)

type Bus interface {
	Publish(context.Context, string, []byte) error
	Health() HealthStatus
}

type Interpreter struct {
	Runtime StepRuntime
	Bus     Bus
	Topic   string
}

func (i Interpreter) Health() HealthStatus {
	return HealthStatus{Status: "ok", Module: "core.interpreter", RuntimeCap: DefaultStepTimeout, MemoryCapMiB: DefaultStepMemoryMiB}
}

// HandleEvent wires API/GSB ingress into the single Step loop.
func (i Interpreter) HandleEvent(ctx context.Context, event Event) StepOutput {
	output := i.Runtime.Step(ctx, StepInput{Event: event})
	if i.Bus == nil || i.Topic == "" || output.Status != "ok" {
		return output
	}
	_ = i.Bus.Publish(ctx, i.Topic, []byte(output.EventID))
	return output
}

func NewDefaultRuntime(resolver Resolver, trisca TRISCAEngine, policy PolicyEngine, action ActionExecutor, meta MetaEngine) StepRuntime {
	return StepRuntime{
		Resolver: resolver,
		TRISCA:   trisca,
		Policy:   policy,
		Action:   action,
		Meta:     meta,
		Timeout:  DefaultStepTimeout,
	}
}
