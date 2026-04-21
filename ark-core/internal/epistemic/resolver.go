package epistemic

// Candidate is a scored claim considered by the resolver.
type Candidate struct {
	ClaimID    string  `json:"claim_id"`
	Score      float64 `json:"score"`
	Confidence float64 `json:"confidence"`
}

// TopCandidate returns the best candidate by score, then by confidence.
func TopCandidate(candidates []Candidate) (Candidate, bool) {
	if len(candidates) == 0 {
		return Candidate{}, false
	}

	best := candidates[0]
	for _, candidate := range candidates[1:] {
		if candidate.Score > best.Score {
			best = candidate
			continue
		}
		if candidate.Score == best.Score && candidate.Confidence > best.Confidence {
			best = candidate
		}
	}

	return best, true
}
