package redteam

import "context"

type Result struct {
	Name     string   `json:"name"`
	Passed   bool     `json:"passed"`
	Severity string   `json:"severity"`
	Evidence []string `json:"evidence,omitempty"`
	Recovery string   `json:"recovery,omitempty"`
}

type Scenario interface {
	Name() string
	Category() string
	Run(ctx context.Context) Result
}

type Runner struct {
	scenarios []Scenario
}

func New(scenarios ...Scenario) *Runner {
	return &Runner{scenarios: scenarios}
}

func (r *Runner) RunAll(ctx context.Context) []Result {
	out := make([]Result, 0, len(r.scenarios))
	for _, s := range r.scenarios {
		out = append(out, s.Run(ctx))
	}
	return out
}

func (r *Runner) RunCategory(ctx context.Context, category string) []Result {
	out := []Result{}
	for _, s := range r.scenarios {
		if s.Category() == category {
			out = append(out, s.Run(ctx))
		}
	}
	return out
}
