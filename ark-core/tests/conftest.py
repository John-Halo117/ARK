"""ark-core pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Return the ark-core project root for local test execution."""

    return Path(__file__).resolve().parents[1]
