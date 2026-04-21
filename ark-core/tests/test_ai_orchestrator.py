"""Orchestrator scaffold checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_orchestrator_dry_run(project_root: Path, tmp_path: Path) -> None:
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            [
                {
                    "id": "docs-pass",
                    "summary": "refresh truth spine links",
                    "scope": "S1",
                    "todo": "T1",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/ai/orchestrator.py",
            "--tasks",
            str(task_file),
            "--dry-run",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["status"] == "dry_run"
