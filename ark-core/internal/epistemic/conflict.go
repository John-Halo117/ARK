package epistemic

// ConflictGroup preserves disagreement in the graph while SSOT stays singular.
type ConflictGroup struct {
	ID              string   `json:"id"`
	Subject         string   `json:"subject"`
	Predicate       string   `json:"predicate"`
	TimeWindow      int64    `json:"time_window"`
	Claims          []string `json:"claims,omitempty"`
	VarianceScore   float64  `json:"variance_score"`
	SourceDiversity float64  `json:"source_diversity"`
	AgreementRatio  float64  `json:"agreement_ratio"`
}

// NeedsReview reports whether the conflict carries enough pressure to slow
// promotion or require higher confidence before projection.
//
// A zero-value ConflictGroup (no claims, no scores) is considered benign and
// does not need review. Once any signal is populated, the check activates.
func (c ConflictGroup) NeedsReview() bool {
	hasSignals := c.VarianceScore != 0 || c.SourceDiversity != 0 || c.AgreementRatio != 0
	if !hasSignals {
		return false
	}
	return c.VarianceScore > 0 || c.SourceDiversity > 0 || c.AgreementRatio < 1
}
