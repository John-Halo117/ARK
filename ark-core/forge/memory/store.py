"""Persistent local storage for Forge state."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..types import CritiqueSummary, EvaluationResult, ForgeState, VerifySummary
from .ban import BanList

MAX_HISTORY = 16


def default_state_path(repo_root: Path) -> Path:
    """Return the default Forge state file location."""

    return repo_root / ".forge" / "state.json"


def load_state(path: Path, *, fallback_lkg: str) -> tuple[ForgeState, BanList]:
    """Load persisted state and failure memory."""

    if not path.exists():
        return ForgeState(lkg_id=fallback_lkg), BanList()
    payload = json.loads(path.read_text(encoding="utf-8"))
    state_payload = payload.get("state", {})
    state = ForgeState(
        lkg_id=str(state_payload.get("lkg_id", fallback_lkg)),
        attempt=int(state_payload.get("attempt", 0)),
        planner_calls=int(state_payload.get("planner_calls", 0)),
        evaluations=[
            _evaluation_from_payload(item)
            for item in state_payload.get("evaluations", [])
        ][-MAX_HISTORY:],
    )
    banlist = BanList.from_payload(payload.get("banlist", []))
    return state, banlist


def save_state(path: Path, state: ForgeState, banlist: BanList) -> None:
    """Persist bounded state and ban memory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    state_payload = asdict(state)
    state_payload["evaluations"] = state_payload["evaluations"][-MAX_HISTORY:]
    payload = {"state": state_payload, "banlist": banlist.export()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _evaluation_from_payload(payload: dict[str, object]) -> EvaluationResult:
    critique_payload = dict(payload.get("critique", {}))
    verify_payload = dict(payload.get("verify", {}))
    return EvaluationResult(
        candidate_id=str(payload.get("candidate_id", "")),
        blocked=bool(payload.get("blocked", False)),
        critique=CritiqueSummary(
            risk=float(critique_payload.get("risk", 1.0)),
            findings=tuple(critique_payload.get("findings", [])),
            attackers={
                str(key): float(value)
                for key, value in dict(critique_payload.get("attackers", {})).items()
            },
            counterfactuals=tuple(critique_payload.get("counterfactuals", [])),
        ),
        verify=VerifySummary(
            tests_ok=bool(verify_payload.get("tests_ok", False)),
            synth_ok=bool(verify_payload.get("synth_ok", False)),
            lint_ok=bool(verify_payload.get("lint_ok", False)),
            types_ok=bool(verify_payload.get("types_ok", False)),
            coverage_delta=float(verify_payload.get("coverage_delta", -1.0)),
            no_new_failures=bool(verify_payload.get("no_new_failures", False)),
            details=dict(verify_payload.get("details", {})),
        ),
        detail=str(payload.get("detail", "")),
        diff_cost=float(payload.get("diff_cost", 1.0)),
        score=float(payload.get("score", 0.0)),
    )
