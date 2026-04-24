"""Runtime guards for bounded Forge execution."""

from __future__ import annotations

from ..types import Mode

MAX_ITERATIONS = 10
MAX_BRANCHES = 3


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a score into a bounded range."""

    return max(low, min(high, value))


def bounded_candidates(mode: Mode) -> int:
    """Return the branch count allowed for a search mode."""

    return {"SIMPLE": 1, "BISECT": 2, "TRISECT": 3}[mode]


def ensure_iteration_budget(attempt: int, limit: int = MAX_ITERATIONS) -> None:
    """Reject unbounded iteration growth."""

    if attempt >= limit:
        raise RuntimeError(f"iteration budget exceeded: {attempt} >= {limit}")


def looks_like_unified_diff(text: str) -> bool:
    """Accept only git-header unified diff payloads."""

    stripped = text.strip()
    return stripped.startswith("diff --git ")


def strip_code_fences(text: str) -> str:
    """Remove simple markdown fences around model output."""

    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    parts = stripped.split("```")
    return parts[1].strip() if len(parts) >= 3 else stripped


def extract_unified_diff(text: str) -> str:
    """Extract the first unified diff block from a noisy model response."""

    cleaned = strip_code_fences(text)
    start = cleaned.find("diff --git ")
    if start < 0:
        raise ValueError("Forge requires unified diff output only")
    candidate = cleaned[start:].strip()
    if not looks_like_unified_diff(candidate):
        raise ValueError("Forge requires unified diff output only")
    return candidate


def require_unified_diff(text: str) -> str:
    """Normalize and validate a diff payload."""

    return extract_unified_diff(text)
