"""Smoke tests: coroutine signatures and import hygiene."""

import importlib.util
import inspect
from pathlib import Path


def _load(project_root: Path, rel: Path, name: str):
    path = project_root / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_functions_are_async(project_root: Path) -> None:
    mesh = _load(project_root, Path("mesh") / "registry.py", "mesh")
    bridge = _load(
        project_root,
        Path("agents") / "composio_bridge" / "bridge.py",
        "bridge",
    )
    assert inspect.iscoroutinefunction(mesh.run)
    assert inspect.iscoroutinefunction(bridge.run)
