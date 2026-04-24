#!/usr/bin/env python3
"""Repo-root Forge launcher."""

from __future__ import annotations

import sys
from pathlib import Path

ARK_ROOT = Path(__file__).resolve().parents[2]
ARK_CORE_ROOT = ARK_ROOT / "ark-core"
if str(ARK_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(ARK_CORE_ROOT))

from forge.ui.launcher import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
