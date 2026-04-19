package gitcommit

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestSourceLoadPreservesSingleLineSubject(t *testing.T) {
	repo := initTestRepo(t)
	sha := commitFile(t, repo, "a.txt", "first\n", "single subject")

	payload, err := (Source{}).Load(context.Background(), repo, sha)
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if payload.Message != "single subject" {
		t.Fatalf("unexpected message: %q", payload.Message)
	}
	if payload.Diff == "" {
		t.Fatal("expected diff to be populated")
	}
}

func TestSourceLoadPreservesMultilineSubjectAndBody(t *testing.T) {
	repo := initTestRepo(t)
	sha := commitFile(t, repo, "b.txt", "next\n", "subject line\n\nbody line")

	payload, err := (Source{}).Load(context.Background(), repo, sha)
	if err != nil {
		t.Fatalf("load failed: %v", err)
	}
	if payload.Message != "subject line\n\nbody line" {
		t.Fatalf("unexpected message: %q", payload.Message)
	}
}

func initTestRepo(t *testing.T) string {
	t.Helper()
	repo := t.TempDir()
	runGit(t, repo, "init")
	runGit(t, repo, "config", "user.name", "Test User")
	runGit(t, repo, "config", "user.email", "test@example.com")
	return repo
}

func commitFile(t *testing.T, repo, name, contents, message string) string {
	t.Helper()
	if err := os.WriteFile(filepath.Join(repo, name), []byte(contents), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}
	runGit(t, repo, "add", name)
	runGit(t, repo, "commit", "-m", message)
	return runGit(t, repo, "rev-parse", "HEAD")
}

func runGit(t *testing.T, repo string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v failed: %v\n%s", args, err, string(out))
	}
	return stringTrim(string(out))
}

func stringTrim(v string) string {
	for len(v) > 0 && (v[len(v)-1] == '\n' || v[len(v)-1] == '\r') {
		v = v[:len(v)-1]
	}
	return v
}
