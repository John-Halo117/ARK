"""Persisted Forge UI session state."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..runtime.config import DEFAULT_UI_STATE_CONFIG


def default_session_path(repo_root: Path) -> Path:
    """Return the default persisted Forge session file."""

    return repo_root / ".forge" / "session.json"


def default_controls() -> dict[str, Any]:
    """Return the shared UI control defaults."""

    return {
        "auto": False,
        "apply": True,
        "planner": False,
        "redteam": False,
        "debug": False,
        "mode_override": DEFAULT_UI_STATE_CONFIG.mode_override,
        "risk_threshold": DEFAULT_UI_STATE_CONFIG.risk_threshold,
        "context_level": DEFAULT_UI_STATE_CONFIG.context_level,
        "test_mode": DEFAULT_UI_STATE_CONFIG.test_mode,
        "tool_profile": DEFAULT_UI_STATE_CONFIG.tool_profile,
    }


def default_machine_state() -> dict[str, Any]:
    """Return the shared machine-state defaults."""

    return {
        "status": "WAITING",
        "stage": "idle",
        "stage_label": "idle",
        "phi": 0.0,
        "qts": 0.0,
        "h": 0.0,
        "g": 0.0,
        "r": 0.0,
        "d": 0.0,
        "mode": "AUTO",
        "branch_count": 0,
        "ban_hits": 0,
        "last_event": "ready",
        "risk_threshold": DEFAULT_UI_STATE_CONFIG.risk_threshold,
        "task": "",
        "mode_override": DEFAULT_UI_STATE_CONFIG.mode_override,
        "context_level": DEFAULT_UI_STATE_CONFIG.context_level,
        "test_mode": DEFAULT_UI_STATE_CONFIG.test_mode,
        "tool_profile": DEFAULT_UI_STATE_CONFIG.tool_profile,
    }


@dataclass(frozen=True)
class AppliedDeltaRecord:
    """One applied delta remembered for safe revert."""

    identifier: str
    label: str
    task: str
    source: str
    patch_text: str
    revert_patch: str
    files_touched: tuple[str, ...] = ()
    patch_path: str | None = None
    timestamp: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AppliedDeltaRecord":
        return cls(
            identifier=str(payload.get("identifier", "")),
            label=str(payload.get("label", "")),
            task=str(payload.get("task", "")),
            source=str(payload.get("source", "")),
            patch_text=str(payload.get("patch_text", "")),
            revert_patch=str(payload.get("revert_patch", "")),
            files_touched=tuple(str(item) for item in payload.get("files_touched", [])),
            patch_path=str(payload.get("patch_path"))
            if payload.get("patch_path")
            else None,
            timestamp=float(payload.get("timestamp", 0.0)),
        )


@dataclass
class ForgeSession:
    """Persisted UI session shared by the Forge launch surfaces."""

    task_text: str = ""
    files_text: str = ""
    controls: dict[str, Any] = field(default_factory=default_controls)
    machine_state: dict[str, Any] = field(default_factory=default_machine_state)
    runtime_summary: str = DEFAULT_UI_STATE_CONFIG.runtime_summary
    selected_candidate_id: str | None = None
    selected_record_id: str | None = None
    live_candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    resume_request: dict[str, Any] | None = None
    applied_history: list[AppliedDeltaRecord] = field(default_factory=list)
    last_result_artifacts: dict[str, str] = field(default_factory=dict)
    onboarding_seen: bool = False
    last_updated: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["logs"] = self.logs[-DEFAULT_UI_STATE_CONFIG.max_logs :]
        payload["applied_history"] = [
            item.as_dict()
            for item in self.applied_history[-DEFAULT_UI_STATE_CONFIG.max_applied :]
        ]
        return payload


def load_session(path: Path) -> ForgeSession:
    """Load a persisted Forge UI session."""

    if not path.exists():
        return ForgeSession()
    payload = json.loads(path.read_text(encoding="utf-8"))
    controls = default_controls()
    controls.update(dict(payload.get("controls", {})))
    machine_state = default_machine_state()
    machine_state.update(dict(payload.get("machine_state", {})))
    return ForgeSession(
        task_text=str(payload.get("task_text", "")),
        files_text=str(payload.get("files_text", "")),
        controls=controls,
        machine_state=machine_state,
        runtime_summary=str(
            payload.get("runtime_summary", DEFAULT_UI_STATE_CONFIG.runtime_summary)
        ),
        selected_candidate_id=str(payload.get("selected_candidate_id"))
        if payload.get("selected_candidate_id")
        else None,
        selected_record_id=str(payload.get("selected_record_id"))
        if payload.get("selected_record_id")
        else None,
        live_candidates={
            str(key): dict(value)
            for key, value in dict(payload.get("live_candidates", {})).items()
        },
        logs=[str(item) for item in payload.get("logs", [])][
            -DEFAULT_UI_STATE_CONFIG.max_logs :
        ],
        resume_request=dict(payload.get("resume_request", {}))
        if payload.get("resume_request")
        else None,
        applied_history=[
            AppliedDeltaRecord.from_payload(dict(item))
            for item in payload.get("applied_history", [])
        ][-DEFAULT_UI_STATE_CONFIG.max_applied :],
        last_result_artifacts={
            str(key): str(value)
            for key, value in dict(payload.get("last_result_artifacts", {})).items()
        },
        onboarding_seen=bool(payload.get("onboarding_seen", False)),
        last_updated=float(payload.get("last_updated", 0.0)),
    )


def save_session(path: Path, session: ForgeSession) -> None:
    """Persist the shared Forge UI session."""

    path.parent.mkdir(parents=True, exist_ok=True)
    session.last_updated = time.time()
    path.write_text(json.dumps(session.as_dict(), indent=2), encoding="utf-8")
