package models

import (
	"testing"
	"time"

	"github.com/John-Halo117/ARK/ark-core/internal/epistemic"
)

func TestClaimCarriesEpistemicState(t *testing.T) {
	t.Parallel()

	now := time.Now().UTC()
	claim := Claim{
		FactID:          "fact-1",
		Subject:         "entity-1",
		Predicate:       "status",
		ObjectValue:     "active",
		ValidTime:       &now,
		Confidence:      0.9,
		State:           epistemic.Linked,
		ConflictGroupID: "group-1",
		PolicyVersion:   "policy-v1",
	}

	if claim.State != epistemic.Linked {
		t.Fatalf("expected linked state, got %s", claim.State)
	}
	if claim.ConflictGroupID == "" {
		t.Fatal("expected conflict group id")
	}
}

func TestSSOTRecordTracksLineageAndSupport(t *testing.T) {
	t.Parallel()

	record := SSOTRecord{
		SSOTKey:          "entity-1.status",
		CurrentValue:     "active",
		PolicyVersion:    "policy-v1",
		DerivedFrom:      []string{"fact-1", "fact-2"},
		SupportStrength:  0.85,
		ConflictPressure: 0.15,
		UpdatedAt:        time.Now().UTC(),
	}

	if len(record.DerivedFrom) != 2 {
		t.Fatalf("expected 2 lineage pointers, got %d", len(record.DerivedFrom))
	}
	if record.SupportStrength <= record.ConflictPressure {
		t.Fatal("expected stronger support than conflict pressure for this fixture")
	}
}
