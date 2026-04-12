"""Tests for AAR runtime helpers."""

import importlib.util
from pathlib import Path


def _load_runtime(project_root: Path):
    path = project_root / "runtime" / "runtime.py"
    spec = importlib.util.spec_from_file_location("ark_runtime", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_worker(project_root: Path):
    path = project_root / "duckdb" / "worker.py"
    spec = importlib.util.spec_from_file_location("ark_duckdb_worker", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_verify_db_read_false_when_missing(project_root: Path, tmp_path: Path) -> None:
    mod = _load_runtime(project_root)
    missing = tmp_path / "nope.duckdb"
    assert mod.verify_db_read(str(missing)) is False


def test_verify_db_read_true_when_valid(project_root: Path, tmp_path: Path) -> None:
    mod = _load_runtime(project_root)
    w = _load_worker(project_root)
    db_path = tmp_path / "x.duckdb"
    w.ensure_db(str(db_path))
    assert mod.verify_db_read(str(db_path)) is True
