"""Phi control field implementation."""

from __future__ import annotations

from ..runtime.guards import clamp
from ..types import EvaluationResult, PhiSnapshot
from .decay import decayed_mean


def _quality(evaluations: list[EvaluationResult]) -> float:
    if not evaluations:
        return 0.55
    values = [1.0 if item.verify.passed() else 0.0 for item in reversed(evaluations)]
    return decayed_mean(values, 2.5)


def _winner_clarity(evaluations: list[EvaluationResult]) -> float:
    if not evaluations:
        return 0.2
    scores = sorted((item.score for item in evaluations), reverse=True)
    if len(scores) == 1:
        return clamp(scores[0])
    return clamp(scores[0] - scores[1] + 0.2)


def _risk(evaluations: list[EvaluationResult], repeated_failures: int) -> float:
    if not evaluations:
        return clamp(0.1 + (0.08 * repeated_failures))
    values = [item.critique.risk for item in reversed(evaluations)]
    return decayed_mean(values, 3.0)


def _diff_cost(evaluations: list[EvaluationResult]) -> float:
    if not evaluations:
        return 0.05
    values = [item.diff_cost for item in reversed(evaluations)]
    return decayed_mean(values, 2.0)


def _entropy(missing_context: int, repeated_failures: int) -> float:
    return clamp(0.2 + (missing_context * 0.12) + (repeated_failures * 0.12))


def compute_phi(
    evaluations: list[EvaluationResult],
    *,
    missing_context: int,
    repeated_failures: int,
) -> PhiSnapshot:
    """Compute the single control value that drives Forge."""

    qts = _quality(evaluations)
    h = _entropy(missing_context, repeated_failures)
    g = _winner_clarity(evaluations)
    r = _risk(evaluations, repeated_failures)
    d = _diff_cost(evaluations)
    value = clamp(
        0.45 + (0.35 * qts) - (0.25 * h) + (0.2 * g) - (0.35 * r) - (0.15 * d)
    )
    return PhiSnapshot(value=value, qts=qts, h=h, g=g, r=r, d=d)
