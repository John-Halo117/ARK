"""Bounded local Docker integration adapters."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

from ark.config import IntegrationConfig
from ark.security import sanitize_string, validate_docker_arg

from .contracts import IntegrationHealth, IntegrationRequest, IntegrationResult, failure, success

CommandRunner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


def _run_command(command: Sequence[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_s,
    )


@dataclass(frozen=True)
class DockerStatusAdapter:
    config: IntegrationConfig
    runner: CommandRunner = _run_command
    capability: str = "system.docker.status"

    def health(self) -> IntegrationHealth:
        ok = shutil.which(self.config.docker_cli) is not None
        detail = "docker CLI available" if ok else "Docker CLI not found"
        return IntegrationHealth(self.capability, ok, detail)

    def execute(self, _request: IntegrationRequest) -> IntegrationResult:
        cli = _safe_docker_cli(self.config.docker_cli)
        if shutil.which(cli) is None:
            return failure(self.capability, "DOCKER_CLI_MISSING", "Docker CLI not found")
        try:
            completed = self.runner((cli, "info", "--format", "{{json .}}"), self.config.docker_timeout_s)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return failure(self.capability, "DOCKER_STATUS_FAILED", str(exc), context={"cli": cli})
        return _status_result(self.capability, completed)


def _safe_docker_cli(value: str) -> str:
    return validate_docker_arg(sanitize_string(value, 128))


def _status_result(capability: str, completed: subprocess.CompletedProcess[str]) -> IntegrationResult:
    if completed.returncode != 0:
        return failure(capability, "DOCKER_DAEMON_UNAVAILABLE", _stderr(completed))
    return success(capability, _status_payload(completed.stdout))


def _status_payload(stdout: str) -> dict[str, object]:
    parsed = _parse_info(stdout)
    return {
        "docker_ready": True,
        "server_version": sanitize_string(str(parsed.get("ServerVersion", "")), 64),
        "containers": int(parsed.get("Containers", 0) or 0),
        "images": int(parsed.get("Images", 0) or 0),
    }


def _parse_info(stdout: str) -> dict[str, object]:
    try:
        parsed = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stderr(completed: subprocess.CompletedProcess[str]) -> str:
    text = completed.stderr or completed.stdout or "docker status failed"
    return sanitize_string(text.strip(), 1024)
