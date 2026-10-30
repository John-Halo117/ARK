"""Keep secrets out of public repository and deployment logs.

Static regression checks; a passing result is not proof of production security.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_production_config_is_private():
    assert not (ROOT / ".env.prod").exists()
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.prod" in ignored
    assert ".env" in ignored
    assert (ROOT / ".env.example").is_file()


def test_init_never_prints_partial_secret_values():
    source = (ROOT / "init-prod.sh").read_text(encoding="utf-8")
    assert "log_pass \"$var = ${val:0:30}...\"" not in source
    assert 'log_pass "$var configured (value withheld)"' in source


def test_deploy_fails_closed_when_private_env_missing():
    source = (ROOT / "deploy-prod.sh").read_text(encoding="utf-8")
    assert 'cp .env.prod .env' not in source
    assert 'if [ ! -f .env ]; then' in source
    assert 'create it privately from .env.example' in source


def test_deployment_shell_syntax():
    for script in ("init-prod.sh", "deploy-prod.sh"):
        run = subprocess.run(["bash", "-n", str(ROOT / script)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
