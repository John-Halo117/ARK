package epistemic

import "testing"

func TestTopCandidateChoosesHighestScoreThenConfidence(t *testing.T) {
	t.Parallel()

	best, ok := TopCandidate([]Candidate{
		{ClaimID: "claim-a", Score: 0.8, Confidence: 0.6},
		{ClaimID: "claim-b", Score: 0.8, Confidence: 0.9},
		{ClaimID: "claim-c", Score: 0.7, Confidence: 1.0},
	})
	if !ok {
		t.Fatal("expected a candidate")
	}
	if best.ClaimID != "claim-b" {
		t.Fatalf("expected claim-b, got %s", best.ClaimID)
	}
}

func TestDecisionAbstainHelpers(t *testing.T) {
	t.Parallel()

	decision := Abstain("rule.safe", "inputs")
	if !decision.Abstained() {
		t.Fatal("expected abstain decision")
	}

	accepted := AcceptCandidate(Candidate{ClaimID: "claim-1", Confidence: 0.75}, "rule.win", "inputs")
	if accepted.Abstained() {
		t.Fatal("expected accepted decision")
	}
	if accepted.AcceptedClaim != "claim-1" {
		t.Fatalf("expected claim-1, got %s", accepted.AcceptedClaim)
	}
}
