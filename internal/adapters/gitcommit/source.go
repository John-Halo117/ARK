package gitcommit

import (
	"context"
	"errors"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/John-Halo117/ARK/arkfield/internal/ingestion"
)

type Source struct{}

func (Source) Load(ctx context.Context, repoPath, commitSHA string) (ingestion.CommitPayload, error) {
	clean := filepath.Clean(repoPath)
	cmd := exec.CommandContext(ctx, "git", "-C", clean, "show", "--format=%an%n%aI%n%B", "--patch", "--no-color", commitSHA)
	out, err := cmd.Output()
	if err != nil {
		return ingestion.CommitPayload{}, err
	}
	parts := strings.SplitN(string(out), "\n", 3)
	if len(parts) < 3 {
		return ingestion.CommitPayload{}, errors.New("unexpected git show output")
	}
	rest := parts[2]
	msgAndDiff := strings.SplitN(rest, "diff --git", 2)
	diff := ""
	if len(msgAndDiff) > 1 {
		diff = "diff --git" + msgAndDiff[1]
	}
	return ingestion.CommitPayload{
		RepoPath: clean,
		SHA:      strings.TrimSpace(commitSHA),
		Author:   strings.TrimSpace(parts[0]),
		Date:     strings.TrimSpace(parts[1]),
		Message:  strings.TrimSpace(msgAndDiff[0]),
		Diff:     strings.TrimSpace(diff),
	}, nil
}
