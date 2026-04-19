package ingestion

import (
	"context"
	"crypto/sha256"
	"crypto/sha3"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
	"github.com/John-Halo117/ARK/arkfield/internal/stability"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

const (
	stateHashKeyPrefix = "ark:statehash:"
	sequenceKey        = "ark:events:sequence"
	subjectName        = "ark.events.cid"
)

type Service struct {
	Redis  *transport.RedisClient
	NATS   *transport.NATSClient
	Kernel *stability.Kernel
}

type IngestRequest struct {
	RepoPath   string            `json:"repo_path"`
	CommitSHA  string            `json:"commit_sha"`
	ParentCID  string            `json:"parent_cid,omitempty"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

type ingestCanonical struct {
	RepoPath  string            `json:"repo_path"`
	CommitSHA string            `json:"commit_sha"`
	Author    string            `json:"author"`
	Date      string            `json:"date"`
	Message   string            `json:"message"`
	Diff      string            `json:"diff"`
	Attrs     map[string]string `json:"attrs,omitempty"`
}

type hashRecord struct {
	CID      string `json:"cid"`
	Sequence uint64 `json:"sequence"`
}

func (s *Service) IngestGitCommit(ctx context.Context, req IngestRequest) (*models.Event, bool, error) {
	if s.Redis == nil || s.NATS == nil || s.Kernel == nil {
		return nil, false, errors.New("service dependencies are not initialized")
	}
	repoPath, err := validateRepoPath(req.RepoPath)
	if err != nil {
		return nil, false, err
	}
	if !isSafeCommitSHA(req.CommitSHA) {
		return nil, false, errors.New("invalid commit sha")
	}

	meta, diff, err := gitShow(ctx, repoPath, req.CommitSHA)
	if err != nil {
		return nil, false, fmt.Errorf("git show failed: %w", err)
	}

	canonicalObj := ingestCanonical{RepoPath: repoPath, CommitSHA: req.CommitSHA, Author: meta.Author, Date: meta.Date, Message: normalizeText(meta.Message), Diff: normalizeText(diff), Attrs: req.Attributes}
	canonicalRaw, err := json.Marshal(canonicalObj)
	if err != nil {
		return nil, false, fmt.Errorf("marshal canonical: %w", err)
	}

	stateHash := sha256Hex(canonicalRaw)
	dedupeKey := stateHashKeyPrefix + stateHash
	if existing, found, err := s.Redis.Get(dedupeKey); err != nil {
		return nil, false, fmt.Errorf("redis read dedupe: %w", err)
	} else if found {
		var rec hashRecord
		if umErr := json.Unmarshal([]byte(existing), &rec); umErr == nil {
			return &models.Event{CID: rec.CID, Sequence: rec.Sequence, StateHash: stateHash, Repo: repoPath, CommitSHA: req.CommitSHA, Author: meta.Author}, true, nil
		}
	}

	seq, err := s.Redis.Incr(sequenceKey)
	if err != nil {
		return nil, false, fmt.Errorf("redis sequence incr: %w", err)
	}

	rawWithSeq, err := json.Marshal(struct {
		StateHash string `json:"state_hash"`
		Sequence  uint64 `json:"sequence"`
		Payload   []byte `json:"payload"`
	}{StateHash: stateHash, Sequence: seq, Payload: canonicalRaw})
	if err != nil {
		return nil, false, fmt.Errorf("marshal cid raw: %w", err)
	}
	cid := cshake256Hex(rawWithSeq)

	decision := s.Kernel.Evaluate(defaultObservation())
	if decision.Freeze {
		return nil, false, fmt.Errorf("stability freeze: %s", decision.Reason)
	}

	event := models.Event{CID: cid, Sequence: seq, StateHash: stateHash, ParentCID: req.ParentCID, Repo: repoPath, CommitSHA: req.CommitSHA, Author: meta.Author, OccurredAt: mustParseTime(meta.Date), Canonical: canonicalRaw, Attributes: req.Attributes, StabilityOK: true}
	data, err := json.Marshal(event)
	if err != nil {
		return nil, false, fmt.Errorf("marshal event: %w", err)
	}
	if err := s.NATS.Publish(subjectName, data); err != nil {
		return nil, false, fmt.Errorf("nats publish: %w", err)
	}

	recordRaw, _ := json.Marshal(hashRecord{CID: cid, Sequence: seq})
	if err := s.Redis.Set(dedupeKey, string(recordRaw)); err != nil {
		return nil, false, fmt.Errorf("redis write dedupe: %w", err)
	}
	return &event, false, nil
}

type gitMeta struct{ Author, Date, Message string }

func gitShow(ctx context.Context, repoPath, commitSHA string) (gitMeta, string, error) {
	cmd := exec.CommandContext(ctx, "git", "-C", repoPath, "show", "--format=%an%n%aI%n%B", "--patch", "--no-color", commitSHA)
	out, err := cmd.Output()
	if err != nil {
		return gitMeta{}, "", err
	}
	parts := strings.SplitN(string(out), "\n", 4)
	if len(parts) < 4 {
		return gitMeta{}, "", errors.New("unexpected git show output")
	}
	meta := gitMeta{Author: strings.TrimSpace(parts[0]), Date: strings.TrimSpace(parts[1])}
	rest := parts[3]
	msgAndDiff := strings.SplitN(rest, "diff --git", 2)
	meta.Message = strings.TrimSpace(msgAndDiff[0])
	if len(msgAndDiff) == 1 {
		return meta, "", nil
	}
	return meta, "diff --git" + msgAndDiff[1], nil
}

func validateRepoPath(path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", errors.New("repo_path is required")
	}
	clean := filepath.Clean(path)
	if strings.Contains(clean, "..") {
		return "", errors.New("repo_path traversal is not allowed")
	}
	return clean, nil
}

func isSafeCommitSHA(v string) bool {
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

func sha256Hex(b []byte) string { sum := sha256.Sum256(b); return hex.EncodeToString(sum[:]) }

func cshake256Hex(raw []byte) string {
	h := sha3.NewCSHAKE256([]byte("ARK-Field-CID"), []byte("git-event"))
	_, _ = h.Write(raw)
	out := make([]byte, 32)
	_, _ = h.Read(out)
	return hex.EncodeToString(out)
}

func defaultObservation() stability.Observation {
	return stability.Observation{CurrentX: 0.4, TargetX: 0.4, Alpha: 0.2, Elapsed: time.Second, TrustSources: []stability.TrustSample{{Weight: 1, Value: 0.4}}, ProbabilityMass: []float64{0.5, 0.5}, VelocityDivergence: 0, RateIn: 1, RateOut: 1, BackpressureEpsilon: 0.1, CurvatureCenter: 0.4, CurvatureNeighbors: []stability.CurvatureNode{{C: 0.4, W: 1}}, SignalA: 0.4, SignalK: 0, SignalGradC: 0, SoftWeights: stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33}, DeltaG: 0, DeltaX: 0, Sigma: 1, CNew: 0.4, COld: 0.4, RecoveryTheta: 0, RecoveryLearningRate: 0.01, RecoveryLossGradient: 0}
}

func mustParseTime(v string) time.Time {
	t, err := time.Parse(time.RFC3339, v)
	if err != nil {
		return time.Now().UTC()
	}
	return t
}
