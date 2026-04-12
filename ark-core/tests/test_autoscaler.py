"""Autoscaler Docker ping."""

from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_autoscaler(project_root: Path):
    import importlib.util

    path = project_root / "autoscaler" / "autoscaler.py"
    spec = importlib.util.spec_from_file_location("ark_autoscaler", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_docker_uses_ping(project_root: Path) -> None:
    mod = _load_autoscaler(project_root)
    mock_client = MagicMock()
    mod.check_docker(mock_client)
    mock_client.ping.assert_called_once()


def test_check_docker_from_env(project_root: Path) -> None:
    mod = _load_autoscaler(project_root)
    with patch("docker.from_env") as from_env:
        client = MagicMock()
        from_env.return_value = client
        mod.check_docker()
        client.ping.assert_called_once()
