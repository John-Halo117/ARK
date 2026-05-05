package stabilitywrap

import "github.com/John-Halo117/ARK/arkfield/internal/stability"

type Evaluator struct {
	Kernel *stability.Kernel
}

func (e Evaluator) Evaluate(observation stability.Observation) stability.Decision {
	return e.Kernel.Evaluate(observation)
}
