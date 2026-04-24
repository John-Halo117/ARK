"""Mode selection and planner policy for Forge."""

from __future__ import annotations

from ..types import Mode


def mode_from_phi(phi: float, entropy: float) -> Mode:
    """Choose a bounded search width from current control conditions."""

    if phi < 0.45 or entropy > 0.55:
        return "TRISECT"
    if phi < 0.7 or entropy > 0.35:
        return "BISECT"
    return "SIMPLE"


def need_planner(
    phi: float,
    entropy: float,
    repeated_failures: int,
    planner_calls: int,
) -> bool:
    """Invoke the larger planner only when search quality degrades."""

    if planner_calls >= 2:
        return False
    return phi < 0.5 or entropy > 0.6 or repeated_failures > 0
