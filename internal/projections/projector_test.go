package projections

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
)

func TestReplayRangeFromQuery(t *testing.T) {
	from, to, err := ReplayRangeFromQuery("1", "3")
	if err != nil || from != 1 || to != 3 {
		t.Fatalf("unexpected parse result: from=%d to=%d err=%v", from, to, err)
	}
	if _, _, err := ReplayRangeFromQuery("x", "3"); err == nil {
		t.Fatal("expected invalid from error")
	}
	if _, _, err := ReplayRangeFromQuery("0", "3"); err == nil {
		t.Fatal("expected zero from to be rejected")
	}
	if _, _, err := ReplayRangeFromQuery("1", "0"); err == nil {
		t.Fatal("expected zero to to be rejected")
	}
	if _, _, err := ReplayRangeFromQuery("5", "3"); err == nil {
		t.Fatal("expected to<from to be rejected")
	}
}

func TestProjectorDuckProjectionAppend(t *testing.T) {
	p := &Projector{DuckDBPath: filepath.Join(t.TempDir(), "duck.ndjson")}
	raw, _ := json.Marshal(models.Event{CID: "cid", Sequence: 1})
	if err := p.appendDuckProjection(raw); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(p.DuckDBPath); err != nil {
		t.Fatal(err)
	}
}

func TestProjectionKey(t *testing.T) {
	if projectionKey(12) != "ark:projection:12" {
		t.Fatal("projection key mismatch")
	}
}

func TestReplayRequiresRedis(t *testing.T) {
	p := &Projector{}
	if _, err := p.Replay(1, 2); err == nil {
		t.Fatal("expected redis required error")
	}
}
