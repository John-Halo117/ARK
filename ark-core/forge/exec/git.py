"""Content-address helpers for LKG and delta identifiers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .runner import validated_command

IGNORE_PARTS = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}
HASH_SUFFIXES = {".py", ".json", ".md", ".sh", ".txt", ".toml", ".yml", ".yaml"}


def delta_id(patch: str) -> str:
    """Create a stable identifier for a delta candidate."""

    return hashlib.sha256(patch.encode("utf-8")).hexdigest()


def next_lkg_id(current_lkg: str, candidate_id: str) -> str:
    """Derive a new content-addressed LKG identifier."""

    material = f"{current_lkg}:{candidate_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def resolve_lkg_id(repo_root: Path) -> str:
    """Return a git commit when available, else fall back to a tree digest."""

    git_path = shutil.which("git")
    if git_path is not None:
        try:
            command = validated_command([git_path, "rev-parse", "HEAD"])
        except ValueError:
            return _tree_digest(repo_root)
        result = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    return _tree_digest(repo_root)


def _tree_digest(repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(_iter_repo_files(repo_root)):
        relative = path.relative_to(repo_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _iter_repo_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_PARTS]
        root_path = Path(root)
        for filename in filenames:
            path = root_path / filename
            if path.suffix in HASH_SUFFIXES or filename in {"go.mod", "go.sum"}:
                files.append(path)
    return files
