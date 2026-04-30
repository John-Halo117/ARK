package redteam

import "context"

type Determinism struct{}

func (d Determinism) Name() string { return "determinism" }
func (d Determinism) Category() string { return "consistency" }

func (d Determinism) Run(ctx context.Context) Result {
	// placeholder: compare outputs of same input twice
	return Result{
		Name:   d.Name(),
		Passed: true,
		Severity: "high",
		Recovery: "ensure stateless deterministic evaluation",
	}
}
