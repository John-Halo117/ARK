from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from ark.git_reconcile import GitReconcileConfig, GitReconciler, git_reconcile_health


def test_push_uses_gcm_first_when_successful(tmp_path: Path):
    runner = RecordingRunner({("git", "push", "origin", "refs/heads/main:refs/heads/main"): _ok("pushed")})
    report = GitReconciler(GitReconcileConfig(repo_root=tmp_path), runner=runner).push_ref("main", "main")

    assert report.status == "ok"
    assert report.pushed_refs == ("main",)
    assert report.operations[0].tier == "gcm"
    assert len(runner.calls) == 1


def test_push_cascades_to_gh_after_gcm_auth_failure(tmp_path: Path):
    gcm = ("git", "push", "origin", "refs/heads/main:refs/heads/main")
    gh = (
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=!/usr/bin/gh auth git-credential",
        "push",
        "origin",
        "refs/heads/main:refs/heads/main",
    )
    runner = RecordingRunner({gcm: _err("auth failed"), gh: _ok("pushed")})
    report = GitReconciler(GitReconcileConfig(repo_root=tmp_path), runner=runner).push_ref("main", "main")

    assert report.status == "ok"
    assert report.operations[0].tier == "gh"
    assert len(runner.calls) == 2


def test_non_fast_forward_push_is_preserved_under_unique_ref(tmp_path: Path):
    primary = ("git", "push", "origin", "refs/heads/feature:refs/heads/feature")
    short = ("git", "rev-parse", "--short", "feature")
    preserved = (
        "git",
        "push",
        "origin",
        "refs/heads/feature:refs/heads/codex/preserved/feature-abc123",
    )
    runner = RecordingRunner(
        {
            primary: _err("rejected non-fast-forward"),
            short: _ok("abc123\n"),
            preserved: _ok("preserved"),
        }
    )

    report = GitReconciler(GitReconcileConfig(repo_root=tmp_path), runner=runner).push_ref("feature", "feature")

    assert report.status == "ok"
    assert report.preserved_refs == ("codex/preserved/feature-abc123",)
    assert runner.calls[-1] == preserved


def test_preserve_stash_branches_and_pushes_stash_commit(tmp_path: Path):
    runner = RecordingRunner(
        {
            ("git", "rev-parse", "stash@{0}"): _ok("deadbeef\n"),
            ("git", "branch", "-f", "codex/stash-backup", "deadbeef"): _ok(""),
            ("git", "push", "origin", "refs/heads/codex/stash-backup:refs/heads/codex/stash-backup"): _ok("pushed"),
        }
    )
    report = GitReconciler(GitReconcileConfig(repo_root=tmp_path), runner=runner).preserve_stash(
        "stash@{0}",
        "codex/stash-backup",
    )

    assert report.status == "ok"
    assert report.pushed_refs == ("codex/stash-backup",)


def test_publish_branches_rejects_unbounded_batch(tmp_path: Path):
    branches = tuple(f"branch-{index}" for index in range(65))
    report = GitReconciler(GitReconcileConfig(repo_root=tmp_path, max_branches=64), runner=RecordingRunner({})).publish_branches(branches)

    assert report.status == "error"
    assert report.issues[0].error_code == "GIT_BRANCH_LIMIT"


def test_health_reports_caps(tmp_path: Path):
    health = git_reconcile_health(GitReconcileConfig(repo_root=tmp_path, timeout_seconds=10, max_branches=4))

    assert health["ok"] is True
    assert health["runtime_cap_seconds"] == 10
    assert health["max_branches"] == 4


class RecordingRunner:
    def __init__(self, responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str], _timeout_s: int, _cwd: Path) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.calls.append(key)
        return self.responses.get(key, _err("missing command"))


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _err(stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
