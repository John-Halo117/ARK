package ingestion

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type fakeSource struct {
	payload CommitPayload
	err     error
}

func (f fakeSource) Load(_ context.Context, _, _ string) (CommitPayload, error) {
	if f.err != nil {
		return CommitPayload{}, f.err
	}
	return f.payload, nil
}

type fakeStore struct {
	rec      DedupeRecord
	found    bool
	pending  bool
	reserved bool
	seq      uint64
	commitErr error
	commits   int
}

func (f *fakeStore) Reserve(string) (bool, error) { return f.reserved, nil }
func (f *fakeStore) Get(string) (DedupeRecord, bool, bool, error) {
	return f.rec, f.found, f.pending, nil
}
func (f *fakeStore) Commit(_ string, rec DedupeRecord) error {
	f.commits++
	if f.commitErr != nil {
		return f.commitErr
	}
	f.rec, f.found = rec, true
	return nil
}
func (f *fakeStore) Release(string) error                    { return nil }
func (f *fakeStore) NextSequence() (uint64, error)           { return f.seq, nil }

type fakePub struct{ published int }

func (f *fakePub) Publish([]byte) error { f.published++; return nil }

type fakeEval struct{ freeze bool }

func (f fakeEval) Evaluate(stability.Observation) stability.Decision {
	return stability.Decision{Freeze: f.freeze, Reason: "frozen"}
}

func TestIngest_DedupedDoesNotPublish(t *testing.T) {
	svc := &Service{
		Source:    fakeSource{payload: CommitPayload{RepoPath: "/tmp/repo", SHA: "abcdef1", Author: "a", Date: time.Now().UTC().Format(time.RFC3339)}},
		Store:     &fakeStore{found: true, rec: DedupeRecord{CID: "cid1", Sequence: 2}},
		Publisher: &fakePub{},
		Stability: fakeEval{},
	}
	evt, deduped, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "/tmp/repo", CommitSHA: "abcdef1"})
	if err != nil || !deduped || evt.CID != "cid1" {
		t.Fatalf("expected deduped event, got evt=%+v deduped=%v err=%v", evt, deduped, err)
	}
}

func TestIngest_PublishesOnce(t *testing.T) {
	pub := &fakePub{}
	store := &fakeStore{reserved: true, seq: 11}
	svc := &Service{
		Source:    fakeSource{payload: CommitPayload{RepoPath: "/tmp/repo", SHA: "abcdef1", Author: "a", Date: time.Now().UTC().Format(time.RFC3339), Message: "m", Diff: "d"}},
		Store:     store,
		Publisher: pub,
		Stability: fakeEval{},
	}
	evt, deduped, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "/tmp/repo", CommitSHA: "abcdef1"})
	if err != nil || deduped {
		t.Fatalf("unexpected err=%v deduped=%v", err, deduped)
	}
	if pub.published != 1 || evt.Sequence != 11 || !store.found {
		t.Fatalf("publish/commit mismatch: published=%d seq=%d found=%v", pub.published, evt.Sequence, store.found)
	}
	if _, err := json.Marshal(evt); err != nil {
		t.Fatalf("event must be json serializable: %v", err)
	}
}

func TestIngest_DoesNotPublishIfCommitFails(t *testing.T) {
	pub := &fakePub{}
	store := &fakeStore{reserved: true, seq: 11, commitErr: errors.New("redis unavailable")}
	svc := &Service{
		Source:    fakeSource{payload: CommitPayload{RepoPath: "/tmp/repo", SHA: "abcdef1", Author: "a", Date: time.Now().UTC().Format(time.RFC3339), Message: "m", Diff: "d"}},
		Store:     store,
		Publisher: pub,
		Stability: fakeEval{},
	}
	_, deduped, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "/tmp/repo", CommitSHA: "abcdef1"})
	if err == nil || !strings.Contains(err.Error(), "dedupe commit") {
		t.Fatalf("expected commit error, got %v", err)
	}
	if deduped {
		t.Fatal("expected non-deduped result")
	}
	if pub.published != 0 {
		t.Fatalf("publish must not happen when commit fails, published=%d", pub.published)
	}
	if store.commits != 1 {
		t.Fatalf("commit should be attempted exactly once, got %d", store.commits)
	}
}

func TestIngest_PendingStateRejected(t *testing.T) {
	svc := &Service{
		Source:    fakeSource{payload: CommitPayload{RepoPath: "/tmp/repo", SHA: "abcdef1", Author: "a", Date: time.Now().UTC().Format(time.RFC3339)}},
		Store:     &fakeStore{pending: true},
		Publisher: &fakePub{},
		Stability: fakeEval{},
	}
	_, _, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "/tmp/repo", CommitSHA: "abcdef1"})
	if err == nil || !strings.Contains(err.Error(), "in progress") {
		t.Fatalf("expected pending conflict error, got %v", err)
	}
}

func TestIngest_StabilityFreezeRejected(t *testing.T) {
	pub := &fakePub{}
	svc := &Service{
		Source:    fakeSource{payload: CommitPayload{RepoPath: "/tmp/repo", SHA: "abcdef1", Author: "a", Date: time.Now().UTC().Format(time.RFC3339)}},
		Store:     &fakeStore{reserved: true, seq: 2},
		Publisher: pub,
		Stability: fakeEval{freeze: true},
	}
	_, _, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "/tmp/repo", CommitSHA: "abcdef1"})
	if err == nil || !strings.Contains(err.Error(), "stability rejected") {
		t.Fatalf("expected stability error, got %v", err)
	}
	if pub.published != 0 {
		t.Fatalf("publish must not happen on freeze")
	}
}

func TestIngest_InvalidInputRejected(t *testing.T) {
	svc := &Service{Source: fakeSource{err: errors.New("boom")}, Store: &fakeStore{}, Publisher: &fakePub{}, Stability: fakeEval{}}
	_, _, err := svc.IngestGitCommit(context.Background(), IngestRequest{RepoPath: "../bad", CommitSHA: "xyz"})
	if err == nil {
		t.Fatal("expected validation error")
	}
}
