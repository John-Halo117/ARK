"""Bounded delta generation for Forge."""

from __future__ import annotations

from ..exec.git import delta_id
from ..runtime.guards import bounded_candidates, require_unified_diff
from ..transform.apply import extract_changed_files, extract_hunk_headers
from ..types import CandidateDelta, ContextBundle, Mode


def propose_deltas(
    context: ContextBundle,
    mode: Mode,
    client: object | None = None,
    *,
    event_sink: object | None = None,
) -> list[CandidateDelta]:
    """Generate between one and three candidate deltas."""

    if context.task.patch:
        candidate = _candidate_from_patch(context.task.patch, "task_patch", 0)
        _emit_candidate(event_sink, candidate)
        return [candidate]
    if client is None:
        return []
    proposals: list[CandidateDelta] = []
    for seed in range(bounded_candidates(mode)):
        try:
            patch = getattr(client, "diff")(context, seed=seed)
        except (RuntimeError, ValueError) as exc:
            _emit_candidate_error(event_sink, seed, str(exc))
            continue
        if not patch:
            continue
        try:
            candidate = _candidate_from_patch(patch, "ollama_executor", seed)
        except ValueError as exc:
            _emit_candidate_error(event_sink, seed, str(exc))
            continue
        proposals.append(candidate)
        _emit_candidate(event_sink, candidate)
    return _dedupe(proposals)


def _candidate_from_patch(patch: str, strategy: str, seed: int) -> CandidateDelta:
    cleaned = require_unified_diff(patch)
    return CandidateDelta(
        identifier=delta_id(cleaned),
        patch=cleaned,
        strategy=strategy,
        seed=seed,
        files_touched=extract_changed_files(cleaned),
    )


def _dedupe(candidates: list[CandidateDelta]) -> list[CandidateDelta]:
    seen: set[str] = set()
    unique: list[CandidateDelta] = []
    for candidate in candidates:
        if candidate.identifier in seen:
            continue
        unique.append(candidate)
        seen.add(candidate.identifier)
    return unique


def _emit_candidate(event_sink: object | None, candidate: CandidateDelta) -> None:
    if event_sink is None:
        return
    event_sink(
        {
            "stage": "candidate_proposed",
            "message": f"proposed {candidate.identifier}",
            "candidate_id": candidate.identifier,
            "strategy": candidate.strategy,
            "seed": candidate.seed,
            "files_touched": list(candidate.files_touched),
            "patch": candidate.patch,
            "hunk_count": len(extract_hunk_headers(candidate.patch)),
            "line_count": sum(
                1
                for line in candidate.patch.splitlines()
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ),
        }
    )


def _emit_candidate_error(event_sink: object | None, seed: int, detail: str) -> None:
    if event_sink is None:
        return
    event_sink(
        {
            "stage": "candidate_skipped",
            "message": f"skipped malformed candidate seed {seed}",
            "seed": seed,
            "detail": detail,
        }
    )
