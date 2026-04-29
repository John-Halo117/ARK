"""Deterministic SD-ARK TRISCA scoring shared by Python planners.

What: computes the same bounded S[6] surface used by the Go core.
Why: Python can select tools and shape DAGs without owning the core loop.
Where: used by Forge-style planners, tool selection, skills, and replay tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from typing import Sequence

MAX_OBSERVATIONS = 6
MAX_TRACE = 6


@dataclass(frozen=True)
class SVector:
    structure: float
    entropy: float
    inequality: float
    temporal: float
    efficiency: float
    signal_density: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (
            self.structure,
            self.entropy,
            self.inequality,
            self.temporal,
            self.efficiency,
            self.signal_density,
        )


@dataclass(frozen=True)
class TRISCAResult:
    s: SVector
    confidence: float
    trace: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "s": {
                "structure": self.s.structure,
                "entropy": self.s.entropy,
                "inequality": self.s.inequality,
                "temporal": self.s.temporal,
                "efficiency": self.s.efficiency,
                "signal_density": self.s.signal_density,
            },
            "confidence": self.confidence,
            "trace": list(self.trace),
        }


def compute_trisca(observations: Sequence[float], *, age_seconds: float = 0.0) -> TRISCAResult:
    """Compute S[6] through a single deterministic path.

    Runtime: O(6). Memory: O(1). Failure: ValueError for non-finite or oversized input.
    """

    if len(observations) > MAX_OBSERVATIONS:
        raise ValueError(f"observations exceed bound: {MAX_OBSERVATIONS}")
    values = [0.0] * MAX_OBSERVATIONS
    for index in range(min(len(observations), MAX_OBSERVATIONS)):
        sample = float(observations[index])
        if not isfinite(sample):
            raise ValueError(f"observation is not finite at index {index}")
        values[index] = _clamp01(sample)

    structure = sum(values) / MAX_OBSERVATIONS
    entropy = _entropy(values)
    inequality = max(values) - min(values)
    temporal = _clamp01(1.0 / (1.0 + abs(float(age_seconds))))
    efficiency = _clamp01(1.0 - ((entropy + inequality) / 2.0))
    signal_density = sum(1 for value in values if value > 0.0) / MAX_OBSERVATIONS
    confidence = _clamp01((structure + efficiency + signal_density + (1.0 - inequality)) / 4.0)
    return TRISCAResult(
        s=SVector(structure, entropy, inequality, temporal, efficiency, signal_density),
        confidence=confidence,
        trace=("normalize", "structure", "entropy", "inequality", "temporal", "efficiency_signal"),
    )


def _entropy(values: Sequence[float]) -> float:
    total = sum(values)
    if total <= 0.0:
        return 0.0
    value = 0.0
    for index in range(min(len(values), MAX_OBSERVATIONS)):
        probability = values[index] / total
        if probability > 0.0:
            value -= probability * log(probability)
    return _clamp01(value / log(MAX_OBSERVATIONS))


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
