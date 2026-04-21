package epistemic

import "testing"

func TestClaimStateIsTerminal(t *testing.T) {
	t.Parallel()

	if !Accepted.IsTerminal() {
		t.Fatal("accepted state must be terminal")
	}
	if !Rejected.IsTerminal() {
		t.Fatal("rejected state must be terminal")
	}
	if Observed.IsTerminal() {
		t.Fatal("observed state must not be terminal")
	}
}
