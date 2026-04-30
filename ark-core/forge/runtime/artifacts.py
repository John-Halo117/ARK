"""Artifact writing for Forge runs."""

from __future__ import annotations

import json
import re
from pathlib import Path


def write_task_artifacts(
    artifacts_dir: Path,
    *,
    task_id: str,
    sequence: int,
    result_payload: dict[str, object],
    accepted_patch: str | None,
) -> dict[str, str]:
    """Write result and patch artifacts for one task execution."""

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    safe_task = _safe_name(task_id)
    prefix = f"{sequence:03d}-{safe_task}"
    result_path = artifacts_dir / f"{prefix}.result.json"
    artifacts = {"result": result_path.as_posix()}
    if accepted_patch is not None:
        patch_path = artifacts_dir / f"{prefix}.accepted.patch"
        patch_path.write_text(accepted_patch, encoding="utf-8")
        artifacts["accepted_patch"] = patch_path.as_posix()
    payload = dict(result_payload)
    payload["artifacts"] = artifacts
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifacts


def _safe_name(task_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", task_id).strip("-") or "task"
