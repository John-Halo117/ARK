"""Simple time-decay helpers used by Phi and failure memory."""

from __future__ import annotations


def decay_weight(age: int, half_life: float) -> float:
    """Return a bounded recency weight for an observation age."""

    if half_life <= 0:
        return 1.0 if age == 0 else 0.0
    return 0.5 ** (age / half_life)


def decayed_mean(values: list[float], half_life: float) -> float:
    """Average values while favoring more recent entries."""

    if not values:
        return 0.0
    weights = [decay_weight(index, half_life) for index in range(len(values))]
    total = sum(weights)
    return (
        sum(value * weight for value, weight in zip(values, weights, strict=True))
        / total
    )


def decayed_overlap(score: float, age: int, half_life: float) -> float:
    """Apply decay to an overlap score."""

    return score * decay_weight(age, half_life)
