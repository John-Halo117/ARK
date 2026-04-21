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
func (c ConflictGroup) NeedsReview() bool {
	return c.VarianceScore > 0 || c.SourceDiversity > 0 || c.AgreementRatio < 1
}
