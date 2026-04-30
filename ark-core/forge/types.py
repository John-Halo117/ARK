"""Shared Forge datatypes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Mode = Literal["SIMPLE", "BISECT", "TRISECT"]
TestMode = Literal["default", "fast", "full"]


@dataclass(frozen=True)
class ForgeTask:
    """Bounded work item accepted by Forge."""

    identifier: str
    summary: str
    scope: str
    todo: str
    target_files: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    patch: str | None = None
    context_level: int = 0
    test_mode: TestMode = "default"


@dataclass(frozen=True)
class CandidateDelta:
    """One reversible delta proposal."""

    identifier: str
    patch: str
    strategy: str
    seed: int
    files_touched: tuple[str, ...]


@dataclass(frozen=True)
class ContextBundle:
    """Deterministic context built from code and task metadata."""

    repo_root: Path
    task: ForgeTask
    target_files: tuple[Path, ...]
    excerpts: dict[str, str]
    ban_hotspots: tuple[str, ...]
    missing_context: int
    plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class PhiSnapshot:
    """Control-field snapshot used for mode selection and acceptance."""

    value: float
    qts: float
    h: float
    g: float
    r: float
    d: float
    threshold: float = 0.4

    def passed(self) -> bool:
        return self.value >= self.threshold


@dataclass(frozen=True)
class CritiqueSummary:
    """Merged red-team output."""

    risk: float
    findings: tuple[str, ...]
    attackers: dict[str, float]
    counterfactuals: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifySummary:
    """Deterministic verification output."""

    tests_ok: bool
    synth_ok: bool
    lint_ok: bool
    types_ok: bool
    coverage_delta: float
    no_new_failures: bool
    details: dict[str, Any] = field(default_factory=dict)

    def passed(self) -> bool:
        return (
            self.tests_ok
            and self.synth_ok
            and self.lint_ok
            and self.types_ok
            and self.no_new_failures
            and self.coverage_delta >= 0.0
        )


@dataclass(frozen=True)
class EvaluationResult:
    """One evaluated delta candidate."""

    candidate_id: str
    blocked: bool
    critique: CritiqueSummary
    verify: VerifySummary
    detail: str
    diff_cost: float
    score: float


@dataclass
class ForgeState:
    """Explicit local state only: the current LKG and evaluation history."""

    lkg_id: str
    attempt: int = 0
    planner_calls: int = 0
    evaluations: list[EvaluationResult] = field(default_factory=list)


@dataclass(frozen=True)
class TaskResult:
    """Operator-visible task status."""

    identifier: str
    status: str
    detail: str
    engine: str
    lkg_id: str
    mode: Mode
    phi: float
    risk: float
    delta_id: str | None = None
    applied: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskExecution:
    """Internal result bundle with an optional accepted candidate."""

    result: TaskResult
    accepted_candidate: CandidateDelta | None = None
    accepted_evaluation: EvaluationResult | None = None
    best_evaluation: EvaluationResult | None = None
