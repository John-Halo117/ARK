"""Tests for duckdb worker (loaded by path to avoid shadowing the duckdb package)."""

import importlib.util
from pathlib import Path


def _load_worker(project_root: Path):
    path = project_root / "duckdb" / "worker.py"
    spec = importlib.util.spec_from_file_location("ark_duckdb_worker", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ensure_db_creates_file(project_root: Path, tmp_path: Path) -> None:
    mod = _load_worker(project_root)
    db_path = tmp_path / "test.duckdb"
    out = mod.ensure_db(str(db_path))
    assert out == str(db_path)
    assert db_path.is_file()
