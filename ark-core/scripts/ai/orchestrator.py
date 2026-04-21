#!/usr/bin/env python3
"""Local-first orchestration scaffold for the ARK coding loop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task:
    """A bounded work item presented to the local orchestrator."""

    identifier: str
    summary: str
    scope: str
    todo: str


@dataclass(frozen=True)
class TaskResult:
    """The outcome of one orchestration pass."""

    identifier: str
    status: str
    detail: str


def load_tasks(path: Path) -> list[Task]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload["tasks"] if isinstance(payload, dict) else payload
    tasks: list[Task] = []
    for idx, item in enumerate(raw_items):
        tasks.append(
            Task(
                identifier=item.get("id", f"task-{idx + 1}"),
                summary=item["summary"],
                scope=item["scope"],
                todo=item["todo"],
            )
        )
    return tasks


def classify(task: Task, repo_root: Path) -> subprocess.CompletedProcess[str]:
    script = repo_root / "scripts" / "ci" / "enforce_tiers.py"
    payload = [{"id": task.identifier, "scope": task.scope, "todo": task.todo}]
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="ark-orchestrator-",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle)
        batch = Path(handle.name)

    try:
        return subprocess.run(
            [
                sys.executable,
                str(script),
                "--rules",
                str(repo_root / "config" / "tiering_rules.json"),
                "--batch",
                str(batch),
            ],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        batch.unlink(missing_ok=True)


def run_gate(command: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def process_task(task: Task, repo_root: Path, dry_run: bool) -> TaskResult:
    tier_check = classify(task, repo_root)

    if tier_check.returncode != 0:
        return TaskResult(task.identifier, "manual_review", tier_check.stderr or tier_check.stdout)

    if dry_run:
        return TaskResult(
            task.identifier,
            "dry_run",
            "classified and ready for test/redteam gates",
        )

    test_result = run_gate(["go", "test", "./..."], repo_root)
    if test_result.returncode != 0:
        return TaskResult(task.identifier, "repair", test_result.stderr or test_result.stdout)

    redteam_result = run_gate(["bash", "scripts/ci/redteam.sh"], repo_root)
    if redteam_result.returncode != 0:
        return TaskResult(task.identifier, "repair", redteam_result.stderr or redteam_result.stdout)

    return TaskResult(task.identifier, "promote", "tests and redteam gate passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True, help="JSON file describing work items")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Path to the ark-core repository root",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after classification instead of invoking gates",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.tasks)
    results = [process_task(task, args.repo_root, args.dry_run) for task in tasks]
    print(json.dumps([result.__dict__ for result in results], indent=2))

    return 0 if all(result.status in {"dry_run", "promote"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
