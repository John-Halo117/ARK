"""Forge persisted session checks."""

from __future__ import annotations

from pathlib import Path

from forge.ui.session import (
    AppliedDeltaRecord,
    ForgeSession,
    load_session,
    save_session,
)


def test_session_round_trip_preserves_controls_and_lineage(tmp_path: Path) -> None:
    session_path = tmp_path / ".forge" / "session.json"
    session = ForgeSession(
        task_text="fix login retry",
        files_text="app/auth.py tests/test_auth.py",
        controls={
            "auto": True,
            "apply": False,
            "planner": True,
            "redteam": True,
            "debug": False,
            "mode_override": "TRISECT",
            "risk_threshold": 0.2,
            "context_level": 2,
            "test_mode": "fast",
        },
        machine_state={
            "status": "INTERRUPTED",
            "stage": "candidate_tests",
            "stage_label": "testing",
            "phi": 0.41,
            "qts": 0.2,
            "h": 0.3,
            "g": 0.1,
            "r": 0.2,
            "d": 0.1,
            "mode": "TRISECT",
            "branch_count": 3,
            "ban_hits": 1,
            "last_event": "interrupted",
            "risk_threshold": 0.2,
            "task": "fix login retry",
            "mode_override": "TRISECT",
            "context_level": 2,
            "test_mode": "fast",
        },
        runtime_summary="Ollama at http://127.0.0.1:11434/api/generate using qwen3-coder:30b",
        selected_candidate_id="delta-1",
        selected_record_id="task-1",
        live_candidates={"delta-1": {"identifier": "delta-1", "status": "testing"}},
        logs=["ready", "running"],
        resume_request={"task_text": "fix login retry", "files": ["app/auth.py"]},
        applied_history=[
            AppliedDeltaRecord(
                identifier="delta-1",
                label="live candidate delta-1",
                task="fix login retry",
                source="live_candidate",
                patch_text="diff --git a/app.py b/app.py\n",
                revert_patch="diff --git a/app.py b/app.py\n",
                files_touched=("app.py",),
            )
        ],
    )

    save_session(session_path, session)
    restored = load_session(session_path)

    assert restored.task_text == "fix login retry"
    assert restored.controls["context_level"] == 2
    assert restored.controls["test_mode"] == "fast"
    assert restored.machine_state["status"] == "INTERRUPTED"
    assert restored.selected_candidate_id == "delta-1"
    assert restored.applied_history[0].files_touched == ("app.py",)
