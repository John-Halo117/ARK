"""Bounded local runtime capability discovery for Forge."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from ..exec.runner import UNSAFE_COMMAND_MESSAGE, validated_command
from .config import DEFAULT_RUNTIME_CAPABILITY_CONFIG, RuntimeCapabilityConfig


@dataclass(frozen=True)
class CapabilityStatus:
    """One detected local tool or integration surface."""

    name: str
    status: str
    detail: str
    recoverable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "recoverable": self.recoverable,
        }


def detect_capabilities(
    repo_root: Path,
    *,
    config: RuntimeCapabilityConfig = DEFAULT_RUNTIME_CAPABILITY_CONFIG,
) -> list[CapabilityStatus]:
    """Detect bounded local tool capabilities for the UI and doctor output."""

    return [
        detect_docker(repo_root, config=config),
        detect_mcp(repo_root, config=config),
    ]


def detect_docker(
    repo_root: Path,
    *,
    config: RuntimeCapabilityConfig = DEFAULT_RUNTIME_CAPABILITY_CONFIG,
) -> CapabilityStatus:
    """Return Docker readiness without starting daemons or containers."""

    docker = _run_command(
        config.docker_version_command, timeout_s=config.command_timeout_s
    )
    if not docker.ok:
        return CapabilityStatus("Docker", "missing", docker.detail, True)
    compose = _run_command(
        config.docker_compose_command, timeout_s=config.command_timeout_s
    )
    if compose.ok:
        detail = _docker_detail(
            repo_root, docker=docker.detail, compose=compose.detail, config=config
        )
        return CapabilityStatus("Docker", "ready", detail, False)
    return CapabilityStatus(
        "Docker", "partial", f"Docker {docker.detail}; Compose unavailable", True
    )


def _docker_detail(
    repo_root: Path,
    *,
    docker: str,
    compose: str,
    config: RuntimeCapabilityConfig,
) -> str:
    compose_file = _first_existing(repo_root, config.docker_compose_files)
    if compose_file is None:
        return f"Docker {docker}; Compose {compose}"
    return f"Docker {docker}; Compose {compose}; project file {compose_file.name}"


def _first_existing(repo_root: Path, relative_paths: tuple[str, ...]) -> Path | None:
    for relative_path in relative_paths:
        path = repo_root / relative_path
        if path.exists():
            return path
    return None


def detect_mcp(
    repo_root: Path,
    *,
    config: RuntimeCapabilityConfig = DEFAULT_RUNTIME_CAPABILITY_CONFIG,
) -> CapabilityStatus:
    """Discover local MCP config files without opening network connections."""

    paths = _mcp_candidate_paths(repo_root, config=config)
    for path in paths[: config.max_mcp_config_files]:
        servers = _read_mcp_servers(path, max_bytes=config.max_mcp_config_bytes)
        if servers:
            detail = f"{len(servers)} MCP server config(s) in {path}"
            return CapabilityStatus("MCP", "configured", detail, False)
    return CapabilityStatus(
        "MCP", "not configured", "No local MCP config file found", True
    )


@dataclass(frozen=True)
class _CommandResult:
    ok: bool
    detail: str


def _run_command(command: tuple[str, ...], *, timeout_s: int) -> _CommandResult:
    if not command or shutil.which(command[0]) is None:
        return _CommandResult(
            False, f"{command[0] if command else 'command'} not found"
        )
    try:
        safe_command = validated_command(command)
    except ValueError:
        return _CommandResult(False, UNSAFE_COMMAND_MESSAGE)
    try:
        result = subprocess.run(
            safe_command, check=False, capture_output=True, text=True, timeout=timeout_s
        )
    except (OSError, subprocess.SubprocessError):
        return _CommandResult(False, "command execution failed")
    output = (result.stdout or result.stderr).strip().splitlines()
    detail = output[0].strip() if output else f"exit {result.returncode}"
    return _CommandResult(result.returncode == 0, detail)


def _mcp_candidate_paths(
    repo_root: Path, *, config: RuntimeCapabilityConfig
) -> list[Path]:
    values = [repo_root / path for path in config.repo_mcp_paths]
    env_path = os.getenv("FORGE_MCP_CONFIG")
    if env_path:
        values.append(Path(env_path).expanduser())
    code_home = os.getenv("CODEX_HOME")
    if code_home:
        values.append(Path(code_home).expanduser() / "config.toml")
    return _dedupe_paths([path for path in values if path.exists()])


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _read_mcp_servers(path: Path, *, max_bytes: int) -> list[str]:
    if path.stat().st_size > max_bytes:
        return []
    if path.suffix.lower() == ".json":
        return _read_json_mcp_servers(path)
    if path.suffix.lower() == ".toml":
        return _read_toml_mcp_servers(path)
    return []


def _read_json_mcp_servers(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = payload.get("mcpServers", {}) if isinstance(payload, dict) else {}
    return list(servers) if isinstance(servers, dict) else []


def _read_toml_mcp_servers(path: Path) -> list[str]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    servers = payload.get("mcp_servers", {}) if isinstance(payload, dict) else {}
    return list(servers) if isinstance(servers, dict) else []
