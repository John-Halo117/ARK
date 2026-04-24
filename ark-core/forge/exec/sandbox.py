"""Candidate isolation for Forge evaluation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

IGNORE = shutil.ignore_patterns(
    ".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "*.pyc"
)


@contextmanager
def sandbox(repo_root: Path):
    """Copy the repo into an isolated temp tree for one candidate."""

    with tempfile.TemporaryDirectory(prefix="forge-") as tempdir:
        target = Path(tempdir) / repo_root.name
        shutil.copytree(repo_root, target, ignore=IGNORE)
        yield target
