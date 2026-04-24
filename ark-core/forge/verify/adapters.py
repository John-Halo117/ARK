"""Verifier-adapter contracts and defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..exec.runner import (
    measure_baseline_coverage,
    run_lint,
    run_pytest_with_coverage,
    run_redteam,
    run_typecheck,
)
from ..types import ContextBundle


@dataclass(frozen=True)
class VerificationRun:
    """Deterministic tool outputs for one sandbox verification pass."""

    tests: dict[str, object]
    lint: dict[str, object]
    types: dict[str, object]
    gate: dict[str, object]
    baseline_coverage: float


class VerifierAdapter(Protocol):
    """Contract for repository verification backends."""

    def baseline_coverage(
        self, repo_root: Path, *, tool_root: Path | None = None
    ) -> float: ...

    def run(
        self,
        context: ContextBundle,
        sandbox_root: Path,
        *,
        tool_root: Path,
        baseline_coverage: float | None = None,
    ) -> VerificationRun: ...


class PythonVerifierAdapter:
    """Default verifier for the current Python-first Forge stack."""

    def baseline_coverage(
        self, repo_root: Path, *, tool_root: Path | None = None
    ) -> float:
        return measure_baseline_coverage(repo_root, tool_root=tool_root)

    def run(
        self,
        context: ContextBundle,
        sandbox_root: Path,
        *,
        tool_root: Path,
        baseline_coverage: float | None = None,
    ) -> VerificationRun:
        baseline = (
            baseline_coverage
            if baseline_coverage is not None
            else self.baseline_coverage(context.repo_root, tool_root=tool_root)
        )
        return VerificationRun(
            tests=run_pytest_with_coverage(
                sandbox_root,
                tool_root=tool_root,
                mode=context.task.test_mode,
                targets=_test_targets(context),
            ),
            lint=run_lint(sandbox_root, tool_root=tool_root),
            types=run_typecheck(sandbox_root, tool_root=tool_root),
            gate=run_redteam(sandbox_root),
            baseline_coverage=baseline,
        )


def _test_targets(context: ContextBundle) -> tuple[str, ...]:
    return tuple(
        item
        for item in context.task.target_files
        if item.startswith("tests/") or Path(item).name.startswith("test_")
    )
