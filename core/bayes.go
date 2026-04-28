package core

import (
	"math"
	"time"
)

const (
	MinProbability = 0.000001
	MaxProbability = 0.999999
)

// UpdateLogOdds applies one bounded Bayesian log-odds update.
func UpdateLogOdds(currentLogOdds float64, prior float64, likelihood float64) (float64, error) {
	if !validProbability(prior) || !validProbability(likelihood) {
		return 0, NewFailure("BAYES_INPUT_INVALID", "prior and likelihood must be finite probabilities in (0,1)", map[string]any{"prior": prior, "likelihood": likelihood}, false)
	}
	priorOdds := math.Log(prior / (1 - prior))
	likelihoodOdds := math.Log(likelihood / (1 - likelihood))
	return currentLogOdds + priorOdds + likelihoodOdds, nil
}

func BayesHealth() HealthStatus {
	return HealthStatus{Status: "ok", Module: "core.bayes", RuntimeCap: time.Millisecond, MemoryCapMiB: 1}
}

func validProbability(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value > MinProbability && value < MaxProbability
}
