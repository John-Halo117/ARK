"""Bounded Git reconciliation module for ARK.

Runtime contract:
- Inputs: GitReconcileConfig plus explicit branch/stash requests.
- Outputs: GitReconcileReport with structured operations and failure issues.
- Constraints: at most max_branches branches per publish call, three auth tiers,
  bounded command timeout, and bounded command output capture.
- Failure cases: invalid refs, command timeouts, auth failure, non-fast-forward
  push rejection, and command execution errors are returned as structured issues.
- Determinism: all command paths are explicit and runner dependencies are injected.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

MAX_BRANCHES = 64
MAX_REF_LENGTH = 192
MAX_OUTPUT_BYTES = 8192
DEFAULT_TIMEOUT_SECONDS = 60
PRESERVE_PREFIX = "codex/preserved"

CommandRunner = Callable[[Sequence[str], int, Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GitIssue:
    status: str
    error_code: str
    reason: str
    context: dict[str, object] = field(default_factory=dict)
    recoverable: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class GitOperation:
    action: str
    status: str
    tier: str
    command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    error_code: str = ""
    remote_ref: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "status": self.status,
            "tier": self.tier,
            "command": list(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_code": self.error_code,
            "remote_ref": self.remote_ref,
        }


@dataclass(frozen=True)
class GitReconcileConfig:
    repo_root: Path
    primary_remote: str = "origin"
    ssh_remote: str = "origin-ssh"
    base_branch: str = "main"
    preserve_prefix: str = PRESERVE_PREFIX
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_branches: int = MAX_BRANCHES


@dataclass(frozen=True)
class GitReconcileReport:
    status: str
    operations: tuple[GitOperation, ...]
    issues: tuple[GitIssue, ...] = ()
    pushed_refs: tuple[str, ...] = ()
    preserved_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "operations": [operation.as_dict() for operation in self.operations],
            "issues": [issue.as_dict() for issue in self.issues],
            "pushed_refs": list(self.pushed_refs),
            "preserved_refs": list(self.preserved_refs),
        }

    def health(self) -> dict[str, object]:
        return {
            "name": "git_reconcile",
            "ok": self.status == "ok",
            "operations": len(self.operations),
            "issues": len(self.issues),
            "pushed_refs": len(self.pushed_refs),
            "preserved_refs": len(self.preserved_refs),
        }


def git_reconcile_health(config: GitReconcileConfig) -> dict[str, object]:
    return {
        "name": "git_reconcile",
        "ok": config.repo_root.exists(),
        "runtime_cap_seconds": config.timeout_seconds,
        "max_branches": config.max_branches,
        "memory_cap_mib": 16,
    }


class GitReconciler:
    def __init__(self, config: GitReconcileConfig, runner: CommandRunner | None = None):
        self.config = config
        self.runner = runner or _run_command

    def publish_branches(self, branches: Sequence[str]) -> GitReconcileReport:
        issue = _validate_config(self.config)
        if issue:
            return GitReconcileReport("error", (), (issue,))
        selected = tuple(branches[: self.config.max_branches])
        if len(branches) > self.config.max_branches:
            return GitReconcileReport(
                "error",
                (),
                (_issue("GIT_BRANCH_LIMIT", "branch publish request exceeds bound", {"max_branches": self.config.max_branches}),),
            )
        operations: list[GitOperation] = []
        issues: list[GitIssue] = []
        pushed: list[str] = []
        preserved: list[str] = []
        fetch = self.fetch()
        operations.extend(fetch.operations)
        issues.extend(fetch.issues)
        if fetch.status != "ok":
            return GitReconcileReport("error", tuple(operations), tuple(issues), tuple(pushed), tuple(preserved))
        for index, branch in enumerate(selected):
            if index >= self.config.max_branches:
                break
            result = self.push_ref(branch, branch)
            operations.extend(result.operations)
            issues.extend(result.issues)
            pushed.extend(result.pushed_refs)
            preserved.extend(result.preserved_refs)
        status = "ok" if not issues else "error"
        return GitReconcileReport(status, tuple(operations), tuple(issues), tuple(pushed), tuple(preserved))

    def preserve_stash(self, stash_ref: str, branch_name: str) -> GitReconcileReport:
        for ref in (stash_ref, branch_name):
            issue = _validate_ref(ref)
            if issue:
                return GitReconcileReport("error", (), (issue,))
        operations: list[GitOperation] = []
        issues: list[GitIssue] = []
        rev = self._run(("git", "rev-parse", stash_ref), "stash-rev", "local")
        operations.append(rev)
        if rev.status != "ok":
            issues.append(_issue("GIT_STASH_MISSING", "stash ref could not be resolved", {"stash_ref": stash_ref}))
            return GitReconcileReport("error", tuple(operations), tuple(issues))
        stash_sha = rev.stdout.strip().splitlines()[0] if rev.stdout.strip() else ""
        if not stash_sha:
            issues.append(_issue("GIT_STASH_MISSING", "stash ref resolved to empty sha", {"stash_ref": stash_ref}))
            return GitReconcileReport("error", tuple(operations), tuple(issues))
        branch = self._run(("git", "branch", "-f", branch_name, stash_sha), "stash-branch", "local")
        operations.append(branch)
        if branch.status != "ok":
            issues.append(_issue("GIT_STASH_BRANCH_FAILED", "stash preservation branch could not be created", {"branch": branch_name}))
            return GitReconcileReport("error", tuple(operations), tuple(issues))
        pushed = self.push_ref(branch_name, branch_name)
        operations.extend(pushed.operations)
        issues.extend(pushed.issues)
        status = "ok" if not issues else "error"
        return GitReconcileReport(status, tuple(operations), tuple(issues), pushed.pushed_refs, pushed.preserved_refs)

    def fetch(self) -> GitReconcileReport:
        result = self._run_cascade(
            action="fetch",
            primary_args=("git", "fetch", "--prune", self.config.primary_remote),
            gh_args=("git", "-c", "credential.helper=", "-c", "credential.helper=!/usr/bin/gh auth git-credential", "fetch", "--prune", self.config.primary_remote),
            ssh_args=("git", "fetch", "--prune", self.config.ssh_remote),
            remote_ref="",
        )
        issue = None if result.status == "ok" else _issue("GIT_FETCH_FAILED", "all fetch auth tiers failed", {"stderr": result.stderr})
        return GitReconcileReport("ok" if issue is None else "error", (result,), () if issue is None else (issue,))

    def push_ref(self, local_ref: str, remote_ref: str) -> GitReconcileReport:
        for ref in (local_ref, remote_ref):
            issue = _validate_ref(ref)
            if issue:
                return GitReconcileReport("error", (), (issue,))
        refspec = f"refs/heads/{local_ref}:refs/heads/{remote_ref}"
        result = self._push_refspec(refspec, remote_ref)
        if result.status == "ok":
            return GitReconcileReport("ok", (result,), pushed_refs=(remote_ref,))
        if not _is_non_fast_forward(result.stderr):
            issue = _issue("GIT_PUSH_FAILED", "all push auth tiers failed", {"remote_ref": remote_ref, "stderr": result.stderr})
            return GitReconcileReport("error", (result,), (issue,))
        preserve_ref = _preserve_ref(self.config.preserve_prefix, local_ref, self._short_ref(local_ref))
        preserve_result = self._push_refspec(f"refs/heads/{local_ref}:refs/heads/{preserve_ref}", preserve_ref)
        if preserve_result.status == "ok":
            return GitReconcileReport("ok", (result, preserve_result), pushed_refs=(preserve_ref,), preserved_refs=(preserve_ref,))
        issue = _issue("GIT_PRESERVE_PUSH_FAILED", "non-fast-forward branch could not be preserved", {"remote_ref": remote_ref, "preserve_ref": preserve_ref})
        return GitReconcileReport("error", (result, preserve_result), (issue,))

    def _push_refspec(self, refspec: str, remote_ref: str) -> GitOperation:
        return self._run_cascade(
            action="push",
            primary_args=("git", "push", self.config.primary_remote, refspec),
            gh_args=("git", "-c", "credential.helper=", "-c", "credential.helper=!/usr/bin/gh auth git-credential", "push", self.config.primary_remote, refspec),
            ssh_args=("git", "push", self.config.ssh_remote, refspec),
            remote_ref=remote_ref,
        )

    def _run_cascade(
        self,
        *,
        action: str,
        primary_args: tuple[str, ...],
        gh_args: tuple[str, ...],
        ssh_args: tuple[str, ...],
        remote_ref: str,
    ) -> GitOperation:
        attempts = (("gcm", primary_args), ("gh", gh_args), ("ssh", ssh_args))
        last = GitOperation(action, "error", "none", (), error_code="GIT_NO_ATTEMPT", remote_ref=remote_ref)
        stderr_parts: list[str] = []
        for index, (tier, args) in enumerate(attempts):
            if index >= 3:
                break
            current = self._run(args, action, tier, remote_ref=remote_ref)
            if current.status == "ok":
                return current
            if current.stderr:
                stderr_parts.append(f"{tier}: {current.stderr}")
            last = current
        if stderr_parts:
            return GitOperation(
                action,
                "error",
                last.tier,
                last.command,
                stdout=last.stdout,
                stderr=_bounded("\n".join(stderr_parts)),
                error_code=last.error_code,
                remote_ref=remote_ref,
            )
        return last

    def _run(self, command: tuple[str, ...], action: str, tier: str, remote_ref: str = "") -> GitOperation:
        try:
            completed = self.runner(command, self.config.timeout_seconds, self.config.repo_root)
        except subprocess.TimeoutExpired as exc:
            return GitOperation(action, "error", tier, command, stderr=_bounded(str(exc)), error_code="GIT_COMMAND_TIMEOUT", remote_ref=remote_ref)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return GitOperation(action, "error", tier, command, stderr=_bounded(str(exc)), error_code="GIT_COMMAND_FAILED", remote_ref=remote_ref)
        status = "ok" if completed.returncode == 0 else "error"
        return GitOperation(
            action=action,
            status=status,
            tier=tier,
            command=command,
            stdout=_bounded(completed.stdout),
            stderr=_bounded(completed.stderr),
            error_code="" if status == "ok" else "GIT_COMMAND_FAILED",
            remote_ref=remote_ref,
        )

    def _short_ref(self, ref: str) -> str:
        result = self._run(("git", "rev-parse", "--short", ref), "short-ref", "local")
        if result.status == "ok" and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
        return "unknown"


def _run_command(command: Sequence[str], timeout_s: int, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_s,
    )


def _validate_config(config: GitReconcileConfig) -> GitIssue | None:
    if config.timeout_seconds <= 0 or config.timeout_seconds > 600:
        return _issue("GIT_TIMEOUT_INVALID", "timeout must be in range 1..600 seconds", {"timeout_seconds": config.timeout_seconds}, False)
    if config.max_branches <= 0 or config.max_branches > MAX_BRANCHES:
        return _issue("GIT_BRANCH_LIMIT_INVALID", "max_branches exceeds module bound", {"max_branches": config.max_branches}, False)
    if not config.repo_root.exists():
        return _issue("GIT_REPO_MISSING", "repo root does not exist", {"repo_root": str(config.repo_root)}, False)
    return None


def _validate_ref(ref: str) -> GitIssue | None:
    if not ref or len(ref) > MAX_REF_LENGTH:
        return _issue("GIT_REF_INVALID", "git ref is empty or too long", {"ref": ref}, False)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-{}@")
    if any(ch not in allowed for ch in ref):
        return _issue("GIT_REF_INVALID", "git ref contains unsupported characters", {"ref": ref}, False)
    if ".." in ref or ref.startswith("/") or ref.endswith("/") or ref.endswith(".lock"):
        return _issue("GIT_REF_INVALID", "git ref contains unsafe path segments", {"ref": ref}, False)
    return None


def _preserve_ref(prefix: str, branch: str, short_sha: str) -> str:
    safe_branch = branch.replace("/", "-")[:96]
    safe_sha = "".join(ch for ch in short_sha if ch.isalnum())[:16] or "unknown"
    return f"{prefix}/{safe_branch}-{safe_sha}"


def _is_non_fast_forward(stderr: str) -> bool:
    text = stderr.lower()
    return "non-fast-forward" in text or "fetch first" in text or "behind its remote" in text


def _bounded(value: str | None) -> str:
    raw = value or ""
    encoded = raw.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return raw
    return encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")


def _issue(error_code: str, reason: str, context: dict[str, object] | None = None, recoverable: bool = True) -> GitIssue:
    return GitIssue("error", error_code, reason, context or {}, recoverable)
