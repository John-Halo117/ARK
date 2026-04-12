"""One-off: copy ark-ssot-mvp into ark-core excluding bulky/runtime paths."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

SRC = Path(r"c:\Users\trevl\OneDrive\Desktop\Home_Sys\Jarvis\ARK\ark\ark-ssot-mvp")
DST = Path(__file__).resolve().parents[1] / "ark-ssot-mvp"

SKIP_DIRS = {"runtime", ".storage", ".git", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv"}
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
    if not SRC.is_dir():
        raise SystemExit(f"Source missing: {SRC}")
    if DST.exists():
        shutil.rmtree(DST)
    DST.parent.mkdir(parents=True, exist_ok=True)
    copy_tree(SRC, DST)
    print(f"Copied to {DST}")


if __name__ == "__main__":
    main()
