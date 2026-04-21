"""Tiering and Red Team script checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_tiering_rules_validate(project_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci/enforce_tiers.py",
            "--rules",
            "config/tiering_rules.json",
            "--validate-rules-only",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_tier_enforcement_blocks_mixed_batches(project_root: Path, tmp_path: Path) -> None:
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(
        json.dumps(
            [
                {"id": "doc-pass", "scope": "S1", "todo": "T1"},
                {"id": "runtime-risk", "scope": "S4", "todo": "T2"},
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci/enforce_tiers.py",
            "--rules",
            "config/tiering_rules.json",
            "--batch",
            str(batch_file),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "mixed scope escalation" in result.stderr


def test_tier_enforcement_blocks_manual_review_priority(
    project_root: Path,
    tmp_path: Path,
) -> None:
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(
        json.dumps([{"id": "policy-upgrade", "scope": "S3", "todo": "T4"}]),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci/enforce_tiers.py",
            "--rules",
            "config/tiering_rules.json",
            "--batch",
            str(batch_file),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "P4 requires manual approval" in result.stderr


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not on PATH")
def test_redteam_gate(project_root: Path) -> None:
    result = subprocess.run(
        ["bash", "scripts/ci/redteam.sh"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
