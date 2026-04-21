package epistemic

// Decision is the final policy outcome applied to a resolver result.
type Decision struct {
	AcceptedClaim string  `json:"accepted_claim,omitempty"`
	RuleID        string  `json:"rule_id"`
	InputsHash    string  `json:"inputs_hash,omitempty"`
	Confidence    float64 `json:"confidence"`
}

// Abstained reports whether policy declined to project a winning claim.
func (d Decision) Abstained() bool {
	return d.AcceptedClaim == ""
}

// AcceptCandidate records a projected candidate under a policy rule.
func AcceptCandidate(candidate Candidate, ruleID, inputsHash string) Decision {
	return Decision{
		AcceptedClaim: candidate.ClaimID,
		RuleID:        ruleID,
		InputsHash:    inputsHash,
		Confidence:    candidate.Confidence,
	}
}

// Abstain records a policy decision to withhold projection.
func Abstain(ruleID, inputsHash string) Decision {
	return Decision{
		RuleID:     ruleID,
		InputsHash: inputsHash,
	}
}
