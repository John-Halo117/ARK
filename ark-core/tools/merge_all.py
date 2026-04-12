"""Merge platform scaffold (Projects\\ark-core) + SSOT MVP into this ark-core folder."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Repo root (ark-core)
HERE = Path(__file__).resolve().parents[1]
PLATFORM_SRC = Path(r"C:\Users\trevl\Projects\ark-core")
SSOT_SRC = Path(r"c:\Users\trevl\OneDrive\Desktop\Home_Sys\Jarvis\ARK\ark\ark-ssot-mvp")
SSOT_DST = HERE / "ark-ssot-mvp"

SKIP_DIRS = {"runtime", ".storage", ".git", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "ark-ssot-mvp"}
SKIP_FILES = {".env"}


def should_skip(root: Path, name: str) -> bool:
    p = root / name
    if name in SKIP_DIRS and p.is_dir():
        return True
    if name in SKIP_FILES and p.is_file():
        return True
    return False


def copy_tree(src: Path, dst: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(src, topdown=True):
        dirnames[:] = [d for d in dirnames if not should_skip(Path(dirpath), d)]
        rel = Path(dirpath).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for fn in filenames:
            if should_skip(Path(dirpath), fn):
                continue
            s = Path(dirpath) / fn
            d = target_dir / fn
            shutil.copy2(s, d)


def main() -> None:
    if not PLATFORM_SRC.is_dir():
        print(f"Skip platform copy: not found {PLATFORM_SRC}", file=sys.stderr)
    else:
        copy_tree(PLATFORM_SRC, HERE)
        print(f"Platform scaffold synced from {PLATFORM_SRC}")

    if not SSOT_SRC.is_dir():
        raise SystemExit(f"SSOT source missing: {SSOT_SRC}")
    if SSOT_DST.exists():
        shutil.rmtree(SSOT_DST)
    SSOT_DST.parent.mkdir(parents=True, exist_ok=True)
    copy_tree(SSOT_SRC, SSOT_DST)
    print(f"SSOT MVP copied to {SSOT_DST}")


if __name__ == "__main__":
    main()
