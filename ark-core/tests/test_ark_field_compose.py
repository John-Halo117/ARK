"""Validate the ARK-Field v4.2 Compose file."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI not on PATH")
def test_ark_field_docker_compose_config(project_root: Path) -> None:
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
