"""Composio bridge env validation."""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_bridge(project_root: Path):
    path = project_root / "agents" / "composio_bridge" / "bridge.py"
    spec = importlib.util.spec_from_file_location("ark_bridge", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_require_composio_key_missing(project_root: Path) -> None:
    mod = _load_bridge(project_root)
    with patch.dict(os.environ, {"COMPOSIO_API_KEY": ""}):
        with pytest.raises(RuntimeError, match="COMPOSIO_API_KEY"):
            mod.require_composio_key()


def test_require_composio_key_present(project_root: Path) -> None:
    mod = _load_bridge(project_root)
    with patch.dict(os.environ, {"COMPOSIO_API_KEY": "secret"}):
        assert mod.require_composio_key() == "secret"


def test_require_composio_key_strips(project_root: Path) -> None:
    mod = _load_bridge(project_root)
    with patch.dict(os.environ, {"COMPOSIO_API_KEY": "  x  "}):
        assert mod.require_composio_key() == "x"


def test_require_composio_key_whitespace_only_raises(project_root: Path) -> None:
    mod = _load_bridge(project_root)
    with patch.dict(os.environ, {"COMPOSIO_API_KEY": "   "}):
        with pytest.raises(RuntimeError, match="COMPOSIO_API_KEY"):
            mod.require_composio_key()
