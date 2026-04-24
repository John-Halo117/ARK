"""Forge TUI helper checks."""

from __future__ import annotations

import json
from pathlib import Path

from forge.ui.app import (
    CandidateRecord,
    artifacts_dir_for_repo,
    history_record_from_result,
    load_history_records,
    render_candidate_summary,
    render_control_panel,
    render_files_panel,
    render_redteam_panel,
    render_status_strip,
    render_test_panel,
)


def test_load_history_records_reads_patch_and_files(tmp_path: Path) -> None:
    artifacts = tmp_path / ".forge" / "artifacts"
    artifacts.mkdir(parents=True)
    patch_path = artifacts / "001-task.accepted.patch"
    patch_path.write_text(
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n",
        encoding="utf-8",
    )
    result_path = artifacts / "001-task.result.json"
    result_path.write_text(
        json.dumps(
            {
                "identifier": "task-1",
                "status": "promote",
                "detail": "all gates passed",
                "phi": 0.72,
                "mode": "BISECT",
                "risk": 0.2,
                "artifacts": {
                    "result": str(result_path),
                    "accepted_patch": str(patch_path),
                },
                "metrics": {
                    "files_touched": ["app.py"],
                    "verify": {
                        "tests_ok": True,
                        "synth_ok": True,
                        "lint_ok": True,
                        "types_ok": True,
                        "coverage_delta": 0.0,
                        "details": {"tests": {"ok": True}},
                    },
                    "critique": {
                        "attackers": {"logic": 0.1},
                        "findings": ["logic: check bounds"],
                        "counterfactuals": ["boundary cases"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    records = load_history_records(artifacts)

    assert len(records) == 1
    assert records[0].identifier == "task-1"
    assert records[0].files_touched == ("app.py",)
    assert "value = 2" in records[0].diff_text


def test_history_helpers_render_panels(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    record = history_record_from_result(
        {
            "identifier": "task-2",
            "status": "promote",
            "detail": "all gates passed",
            "phi": 0.81,
            "mode": "TRISECT",
            "risk": 0.12,
            "applied": True,
            "artifacts": {"result": str(tmp_path / "result.json")},
            "metrics": {
                "files_touched": ["service/retry.py"],
                "verify": {
                    "tests_ok": True,
                    "synth_ok": True,
                    "lint_ok": True,
                    "types_ok": True,
                    "coverage_delta": 0.1,
                    "details": {"tests": {"ok": True, "coverage": 88.5}},
                },
                "critique": {
                    "attackers": {"logic": 0.1, "security": 0.0},
                    "findings": ["logic: removed fallback"],
                    "counterfactuals": ["smallest break"],
                },
            },
        }
    )
    machine = {
        "status": "COMMIT READY",
        "stage_label": "decision",
        "phi": 0.81,
        "qts": 0.6,
        "h": 0.2,
        "g": 0.4,
        "r": 0.1,
        "d": 0.1,
        "mode": "TRISECT",
        "risk_threshold": 0.35,
        "branch_count": 3,
        "ban_hits": 0,
        "last_event": "promote",
    }

    control = render_control_panel("Ollama at x using y", machine, record, debug=False)
    files = render_files_panel(record)
    redteam = render_redteam_panel(record, expanded=True)
    tests = render_test_panel(record, expanded=True)

    assert "COMMIT READY" in control
    assert "service/retry.py" in files
    assert "logic: 0.10" in redteam
    assert "coverage_delta: +0.10" in tests
    assert artifacts_dir_for_repo(repo_root) == repo_root / ".forge" / "artifacts"


def test_candidate_helpers_render_live_state() -> None:
    candidate = CandidateRecord(
        identifier="delta-1234567890",
        status="testing",
        patch="diff --git a/service.py b/service.py\n--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n",
        files_touched=("service.py",),
        strategy="ollama_executor",
        seed=2,
        risk=0.18,
        score=0.77,
        line_count=2,
        hunk_count=1,
        tests_ok=None,
        lint_ok=True,
        types_ok=None,
        synth_ok=None,
        coverage_delta=0.0,
        findings=("logic: tighten bounds",),
        attackers={"logic": 0.2, "security": 0.1},
        counterfactuals=("boundary case",),
        detail="running bounded verification",
    )
    machine = {
        "status": "TESTING",
        "stage": "candidate_tests",
        "stage_label": "testing",
        "task": "fix retry edge case",
        "phi": 0.44,
        "r": 0.18,
        "mode": "TRISECT",
    }

    control = render_control_panel(
        "Ollama at x using y", machine, candidate, debug=False
    )
    strip = render_status_strip(
        "Ollama at x using y",
        machine,
        live_count=1,
        history_count=2,
        selected_label="Δ delta-1234567890",
    )
    files = render_files_panel(candidate)
    redteam = render_redteam_panel(candidate, expanded=True)
    tests = render_test_panel(candidate, expanded=True)
    summary = render_candidate_summary(
        {candidate.identifier: candidate}, candidate.identifier
    )

    assert "Selected Δ: delta-1234567890" in control
    assert "[VERIFY]" in control
    assert "fix retry edge case" in strip
    assert "Live Δ=1" in strip
    assert "service.py" in files
    assert "logic: 0.20" in redteam
    assert "boundary case" in redteam
    assert "tests_ok: pending" in tests
    assert "running bounded verification" in tests
    assert "delta-1234" in summary
