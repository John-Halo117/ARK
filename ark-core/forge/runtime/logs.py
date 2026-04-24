"""Observability helpers for Forge task results."""

from __future__ import annotations

from ..types import EvaluationResult, ForgeState, ForgeTask, Mode, PhiSnapshot


def task_metrics(
    task: ForgeTask,
    state: ForgeState,
    phi: PhiSnapshot,
    mode: Mode,
    evaluation: EvaluationResult | None,
    *,
    ban_hits: int,
) -> dict[str, object]:
    """Return a compact, structured observability record."""

    metrics: dict[str, object] = {
        "task_id": task.identifier,
        "attempt": state.attempt,
        "lkg_id": state.lkg_id,
        "context_level": task.context_level,
        "test_mode": task.test_mode,
        "phi": phi.value,
        "qts": phi.qts,
        "h": phi.h,
        "g": phi.g,
        "r": phi.r,
        "d": phi.d,
        "mode": mode,
        "ban_hits": ban_hits,
    }
    if evaluation is not None:
        metrics.update(
            {
                "delta_id": evaluation.candidate_id,
                "risk": evaluation.critique.risk,
                "tests": evaluation.verify.tests_ok,
                "coverage_delta": evaluation.verify.coverage_delta,
                "detail": evaluation.detail,
            }
        )
    return metrics
