package ingestion

import (
	"context"
	"crypto/sha256"
	"crypto/sha3"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"path/filepath"
	"strings"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type CommitSource interface {
	Load(ctx context.Context, repoPath, commitSHA string) (CommitPayload, error)
}

type DedupeSequencer interface {
	Reserve(stateHash string) (bool, error)
	Get(stateHash string) (DedupeRecord, bool, bool, error)
	Commit(stateHash string, rec DedupeRecord) error
	Release(stateHash string) error
	NextSequence() (uint64, error)
}

type Publisher interface {
	Publish(payload []byte) error
}

type StabilityEvaluator interface {
	Evaluate(observation stability.Observation) stability.Decision
}

type CommitPayload struct {
	RepoPath string
	SHA      string
	Author   string
	Date     string
	Message  string
	Diff     string
}

type DedupeRecord struct {
	CID      string
	Sequence uint64
}

type Service struct {
	Source    CommitSource
	Store     DedupeSequencer
	Publisher Publisher
	Stability StabilityEvaluator
	Observe   func(IngestRequest, CommitPayload) stability.Observation
}

type IngestRequest struct {
	RepoPath   string            `json:"repo_path"`
	CommitSHA  string            `json:"commit_sha"`
	ParentCID  string            `json:"parent_cid,omitempty"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

type canonicalEvent struct {
	RepoPath   string            `json:"repo_path"`
	CommitSHA  string            `json:"commit_sha"`
	Author     string            `json:"author"`
	Date       string            `json:"date"`
	Message    string            `json:"message"`
	Diff       string            `json:"diff"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

func (s *Service) IngestGitCommit(ctx context.Context, req IngestRequest) (*models.Event, bool, error) {
	if err := validateRequest(req); err != nil {
		return nil, false, err
	}
	if s.Source == nil || s.Store == nil || s.Publisher == nil || s.Stability == nil {
		return nil, false, errors.New("ingestion service dependencies are not initialized")
	}

	commit, err := s.Source.Load(ctx, req.RepoPath, req.CommitSHA)
	if err != nil {
		return nil, false, fmt.Errorf("load commit: %w", err)
	}
	canonicalRaw, err := canonicalize(commit, req.Attributes)
	if err != nil {
		return nil, false, err
	}

	stateHash := sha256Hex(canonicalRaw)
	if existing, found, pending, err := s.Store.Get(stateHash); err != nil {
		return nil, false, fmt.Errorf("dedupe read: %w", err)
	} else if found {
		return &models.Event{CID: existing.CID, Sequence: existing.Sequence, StateHash: stateHash, Repo: commit.RepoPath, CommitSHA: commit.SHA, Author: commit.Author}, true, nil
	} else if pending {
		return nil, false, errors.New("ingest already in progress for state hash")
	}

	reserved, err := s.Store.Reserve(stateHash)
	if err != nil {
		return nil, false, fmt.Errorf("dedupe reserve: %w", err)
	}
	if !reserved {
		if existing, found, _, readErr := s.Store.Get(stateHash); readErr == nil && found {
			return &models.Event{CID: existing.CID, Sequence: existing.Sequence, StateHash: stateHash, Repo: commit.RepoPath, CommitSHA: commit.SHA, Author: commit.Author}, true, nil
		}
		return nil, false, errors.New("ingest reservation conflict")
	}

	seq, err := s.Store.NextSequence()
	if err != nil {
		_ = s.Store.Release(stateHash)
		return nil, false, fmt.Errorf("next sequence: %w", err)
	}

	cid := cshake256Hex(serializeCIDSource(stateHash, seq, canonicalRaw))
	obsBuilder := s.Observe
	if obsBuilder == nil {
		obsBuilder = DefaultObservation
	}
	decision := s.Stability.Evaluate(obsBuilder(req, commit))
	if decision.Freeze {
		_ = s.Store.Release(stateHash)
		return nil, false, fmt.Errorf("stability rejected event: %s", decision.Reason)
	}

	event := models.Event{
		CID:         cid,
		Sequence:    seq,
		StateHash:   stateHash,
		ParentCID:   req.ParentCID,
		Repo:        commit.RepoPath,
		CommitSHA:   commit.SHA,
		Author:      commit.Author,
		OccurredAt:  mustParseRFC3339(commit.Date),
		Canonical:   canonicalRaw,
		Attributes:  req.Attributes,
		StabilityOK: true,
	}
	payload, err := json.Marshal(event)
	if err != nil {
		_ = s.Store.Release(stateHash)
		return nil, false, fmt.Errorf("marshal event: %w", err)
	}
	if err := s.Store.Commit(stateHash, DedupeRecord{CID: cid, Sequence: seq}); err != nil {
		_ = s.Store.Release(stateHash)
		return nil, false, fmt.Errorf("dedupe commit: %w", err)
	}
	if err := s.Publisher.Publish(payload); err != nil {
		return nil, false, fmt.Errorf("publish event: %w", err)
	}
	return &event, false, nil
}

func canonicalize(c CommitPayload, attrs map[string]string) ([]byte, error) {
	obj := canonicalEvent{
		RepoPath:   filepath.Clean(c.RepoPath),
		CommitSHA:  strings.ToLower(strings.TrimSpace(c.SHA)),
		Author:     normalizeText(c.Author),
		Date:       strings.TrimSpace(c.Date),
		Message:    normalizeText(c.Message),
		Diff:       normalizeText(c.Diff),
		Attributes: attrs,
	}
	raw, err := json.Marshal(obj)
	if err != nil {
		return nil, fmt.Errorf("marshal canonical: %w", err)
	}
	return raw, nil
}

func validateRequest(req IngestRequest) error {
	if strings.TrimSpace(req.RepoPath) == "" {
		return errors.New("repo_path is required")
	}
	clean := filepath.Clean(req.RepoPath)
	if strings.Contains(clean, "..") {
		return errors.New("repo_path traversal is not allowed")
	}
	if !isSafeCommitSHA(req.CommitSHA) {
		return errors.New("invalid commit_sha")
	}
	return nil
}

func isSafeCommitSHA(v string) bool {
	v = strings.ToLower(strings.TrimSpace(v))
	if len(v) < 7 || len(v) > 64 {
		return false
	}
	for _, r := range v {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	return true
}

func normalizeText(v string) string {
	lines := strings.Split(strings.ReplaceAll(v, "\r\n", "\n"), "\n")
	for i := range lines {
		lines[i] = strings.TrimRight(lines[i], " \t")
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

func sha256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func serializeCIDSource(stateHash string, seq uint64, canonical []byte) []byte {
	raw, _ := json.Marshal(struct {
		StateHash string `json:"state_hash"`
		Sequence  uint64 `json:"sequence"`
		Payload   []byte `json:"payload"`
	}{StateHash: stateHash, Sequence: seq, Payload: canonical})
	return raw
}

func cshake256Hex(raw []byte) string {
	h := sha3.NewCSHAKE256([]byte("ARK-Field-CID"), []byte("git-event"))
	_, _ = h.Write(raw)
	out := make([]byte, 32)
	_, _ = h.Read(out)
	return hex.EncodeToString(out)
}

func mustParseRFC3339(v string) time.Time {
	t, err := time.Parse(time.RFC3339, strings.TrimSpace(v))
	if err != nil {
		return time.Now().UTC()
	}
	return t
}

func DefaultObservation(req IngestRequest, c CommitPayload) stability.Observation {
	_ = req
	diffSize := float64(len(c.Diff))
	msgSize := float64(len(c.Message))
	target := math.Min(1, diffSize/20000)
	current := math.Min(1, msgSize/2000)
	if current == 0 {
		current = 0.01
	}
	deltaX := target - current
	sigma := math.Max(0.05, current*0.2)
	return stability.Observation{
		CurrentX:             current,
		TargetX:              target,
		Alpha:                0.2,
		Elapsed:              time.Second,
		TrustSources:         []stability.TrustSample{{Weight: 0.7, Value: target}, {Weight: 0.3, Value: current}},
		ProbabilityMass:      []float64{0.6, 0.3, 0.1},
		VelocityDivergence:   0,
		RateIn:               1,
		RateOut:              1,
		BackpressureEpsilon:  0.1,
		CurvatureCenter:      current,
		CurvatureNeighbors:   []stability.CurvatureNode{{C: target, W: 1}},
		SignalA:              current,
		SignalK:              target - current,
		SignalGradC:          deltaX,
		SoftWeights:          stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33},
		DeltaG:               0,
		DeltaX:               deltaX,
		Sigma:                sigma,
		CNew:                 target,
		COld:                 current,
		RecoveryTheta:        0,
		RecoveryLearningRate: 0.01,
		RecoveryLossGradient: 0,
	}
}
