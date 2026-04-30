"""Forge security regression checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from forge.exec import git, runner
from forge.models import discovery
from forge.runtime import bootstrap, capabilities


def test_run_command_rejects_unsafe_args_without_execution(
    monkeypatch: object, tmp_path: Path
) -> None:
    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not execute unsafe commands")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = runner.run_command(["python", "bad;arg"], tmp_path)

    assert result == {
        "ok": False,
        "returncode": -2,
        "stdout": "",
        "stderr": runner.UNSAFE_COMMAND_MESSAGE,
        "command": [],
    }
    assert "bad;arg" not in str(result)


def test_resolve_lkg_falls_back_when_git_command_is_unsafe(
    monkeypatch: object, tmp_path: Path
) -> None:
    (tmp_path / "README.md").write_text("safe tree\n", encoding="utf-8")
    monkeypatch.setattr(git.shutil, "which", lambda name: "/usr/bin/git;bad")

    def fail_run(*args, **kwargs):
        raise AssertionError("unsafe git path should not execute")

    monkeypatch.setattr(git.subprocess, "run", fail_run)

    lkg = git.resolve_lkg_id(tmp_path)

    assert len(lkg) == 64


def test_capability_probe_rejects_unsafe_args_without_execution(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(capabilities.shutil, "which", lambda name: "/usr/bin/docker")

    def fail_run(*args, **kwargs):
        raise AssertionError("unsafe capability command should not execute")

    monkeypatch.setattr(capabilities.subprocess, "run", fail_run)

    result = capabilities._run_command(("docker", "bad;arg"), timeout_s=1)

    assert result.ok is False
    assert result.detail == runner.UNSAFE_COMMAND_MESSAGE


def test_discovery_gateway_returns_none_when_validation_fails(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(
        discovery,
        "validated_command",
        lambda command: (_ for _ in ()).throw(ValueError("unsafe secret")),
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("invalid discovery command should not execute")

    monkeypatch.setattr(discovery.subprocess, "run", fail_run)

    assert discovery._default_gateway() is None


def test_bootstrap_rejects_unsafe_background_command(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/ollama")

    def fail_popen(*args, **kwargs):
        raise AssertionError("unsafe background command should not execute")

    monkeypatch.setattr(bootstrap.subprocess, "Popen", fail_popen)

    assert bootstrap._launch_background_command(("ollama", "pull", "bad;model")) is None
