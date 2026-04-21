package epistemic

// ClaimState tracks where a claim sits inside ARK's epistemic pipeline.
type ClaimState string

const (
	Observed  ClaimState = "observed"
	Extracted ClaimState = "extracted"
	Linked    ClaimState = "linked"
	Contested ClaimState = "contested"
	Resolved  ClaimState = "resolved"
	Accepted  ClaimState = "accepted"
	Rejected  ClaimState = "rejected"
)

// IsTerminal reports whether the claim has reached a final state.
func (s ClaimState) IsTerminal() bool {
	return s == Accepted || s == Rejected
}
