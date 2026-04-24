"""Deterministic command execution for Forge verification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def project_python(tool_root: Path) -> str:
    """Prefer the project-local Python environment when present."""

    venv_python = tool_root / ".venv" / "bin" / "python"
    return venv_python.as_posix() if venv_python.exists() else sys.executable


def run_command(command: list[str], cwd: Path, timeout: int = 900) -> dict[str, object]:
    """Run a command with captured output."""

    result = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
    }


def run_pytest_with_coverage(
    repo_root: Path,
    tool_root: Path | None = None,
    *,
    mode: str = "default",
    targets: tuple[str, ...] = (),
) -> dict[str, object]:
    """Run pytest and capture repo-wide coverage."""

    python_bin = project_python(tool_root or repo_root)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        coverage_path = Path(handle.name)
    selected_targets = _pytest_targets(repo_root, mode=mode, targets=targets)
    command = [
        python_bin,
        "-m",
        "pytest",
        "-s",
        "-q",
        "--cov=.",
        f"--cov-report=json:{coverage_path.as_posix()}",
        *selected_targets,
    ]
    result = run_command(command, repo_root)
    result["coverage"] = _read_coverage(coverage_path)
    result["mode"] = mode
    result["selected_targets"] = list(selected_targets)
    coverage_path.unlink(missing_ok=True)
    return result


def run_lint(repo_root: Path, tool_root: Path | None = None) -> dict[str, object]:
    """Run ruff as the lint gate."""

    python_bin = project_python(tool_root or repo_root)
    return run_command([python_bin, "-m", "ruff", "check", "."], repo_root)


def run_typecheck(repo_root: Path, tool_root: Path | None = None) -> dict[str, object]:
    """Use compileall as a deterministic syntax/type floor when no external checker is configured."""

    python_bin = project_python(tool_root or repo_root)
    targets = [
        name for name in ("forge", "scripts/ai", "tests") if (repo_root / name).exists()
    ]
    return run_command([python_bin, "-m", "compileall", "-q", *targets], repo_root)


def run_redteam(repo_root: Path) -> dict[str, object]:
    """Run the repo Red Team gate when present."""

    script = repo_root / "scripts" / "ci" / "redteam.sh"
    if not script.exists():
        return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "command": []}
    return run_command(["bash", "scripts/ci/redteam.sh"], repo_root)


def measure_baseline_coverage(repo_root: Path, tool_root: Path | None = None) -> float:
    """Capture current coverage when the repo is already green enough to measure."""

    result = run_pytest_with_coverage(repo_root, tool_root=tool_root)
    return float(result["coverage"]) if result["ok"] else 0.0


def _read_coverage(path: Path) -> float:
    if not path.exists():
        return 0.0
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return 0.0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0.0
    totals = payload.get("totals", {})
    return float(totals.get("percent_covered", 0.0))


def _pytest_targets(
    repo_root: Path, *, mode: str, targets: tuple[str, ...]
) -> tuple[str, ...]:
    if mode != "fast":
        return ()
    selected = [item for item in targets if _is_pytest_target(repo_root / item)]
    return tuple(selected)


def _is_pytest_target(path: Path) -> bool:
    return (
        path.exists()
        and path.is_file()
        and (path.name.startswith("test_") or path.parent.name == "tests")
    )
