"""Bounded local runtime boot helpers for low-friction Forge startup."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import time

from ..models.discovery import (
    choose_model,
    compact_runtime_summary,
    detect_ollama_endpoint,
)
from ..exec.runner import validated_command
from .config import DEFAULT_RUNTIME_BOOTSTRAP_CONFIG, RuntimeBootstrapConfig


@dataclass(frozen=True)
class RuntimeStatus:
    """One bounded snapshot of Forge runtime readiness."""

    phase: str
    title: str
    message: str
    summary: str
    endpoint: str | None
    model: str | None
    models: tuple[str, ...]
    actions: tuple[str, ...] = ()
    nerd_details: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.endpoint is not None and self.model is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "title": self.title,
            "message": self.message,
            "summary": self.summary,
            "endpoint": self.endpoint,
            "model": self.model,
            "models": list(self.models),
            "actions": list(self.actions),
            "nerd_details": list(self.nerd_details),
            "ready": self.ready,
        }


def detect_runtime_status(
    *,
    preferred_url: str | None = None,
    preferred_model: str | None = None,
    timeout_s: int = DEFAULT_RUNTIME_BOOTSTRAP_CONFIG.detect_timeout_s,
    actions: tuple[str, ...] = (),
    nerd_details: tuple[str, ...] = (),
) -> RuntimeStatus:
    """Return the current local runtime readiness without side effects."""

    endpoint, models = detect_ollama_endpoint(
        preferred_url=preferred_url,
        timeout_s=timeout_s,
    )
    selected_model = choose_model(models, preferred=preferred_model)
    summary = compact_runtime_summary(endpoint, selected_model, models)
    if endpoint is not None and selected_model is not None:
        return RuntimeStatus(
            phase="ready",
            title="AI is ready",
            message="Forge can start working right away.",
            summary=summary,
            endpoint=endpoint,
            model=selected_model,
            models=tuple(models),
            actions=actions,
            nerd_details=nerd_details,
        )
    if endpoint is not None:
        return RuntimeStatus(
            phase="installing",
            title="Finishing AI setup",
            message="Forge found the local AI engine and is preparing a coding model.",
            summary=summary,
            endpoint=endpoint,
            model=selected_model,
            models=tuple(models),
            actions=actions,
            nerd_details=nerd_details,
        )
    return RuntimeStatus(
        phase="starting",
        title="Waking up local AI",
        message="Forge is trying to start the local AI runtime in the background.",
        summary=summary,
        endpoint=endpoint,
        model=selected_model,
        models=tuple(models),
        actions=actions,
        nerd_details=nerd_details,
    )


def ensure_runtime_ready(
    *,
    preferred_url: str | None = None,
    preferred_model: str | None = None,
    config: RuntimeBootstrapConfig = DEFAULT_RUNTIME_BOOTSTRAP_CONFIG,
) -> RuntimeStatus:
    """Attempt a bounded background-friendly runtime boot and return the result."""

    status = detect_runtime_status(
        preferred_url=preferred_url,
        preferred_model=preferred_model,
        timeout_s=config.detect_timeout_s,
    )
    actions: list[str] = []
    nerd_details: list[str] = []
    if status.ready:
        return status
    if status.endpoint is None and config.auto_start_ollama:
        launched = _launch_first_available(config.ollama_start_commands)
        if launched is not None:
            actions.append("Forge started the local AI service in the background.")
            nerd_details.append(launched)
        else:
            actions.append("Forge could not start Ollama automatically.")
            nerd_details.append("No usable Ollama command was found.")
        status = _poll_runtime(
            preferred_url=preferred_url,
            preferred_model=preferred_model,
            config=config,
            actions=tuple(actions),
            nerd_details=tuple(nerd_details),
            require_model=False,
        )
    if status.endpoint is not None and status.model is None and config.auto_pull_model:
        launched = _pull_first_available(
            config=config,
            model=preferred_model or config.bootstrap_model,
        )
        if launched is not None:
            actions.append(
                "Forge is downloading a coding model in the background."
            )
            nerd_details.append(launched)
            status = _poll_runtime(
                preferred_url=preferred_url,
                preferred_model=preferred_model,
                config=config,
                actions=tuple(actions),
                nerd_details=tuple(nerd_details),
                require_model=True,
            )
        elif config.fallback_bootstrap_model != config.bootstrap_model:
            fallback = _pull_first_available(
                config=config,
                model=config.fallback_bootstrap_model,
            )
            if fallback is not None:
                actions.append("Forge is downloading a fallback coding model.")
                nerd_details.append(fallback)
                status = _poll_runtime(
                    preferred_url=preferred_url,
                    preferred_model=preferred_model,
                    config=config,
                    actions=tuple(actions),
                    nerd_details=tuple(nerd_details),
                    require_model=True,
                )
    return detect_runtime_status(
        preferred_url=preferred_url,
        preferred_model=preferred_model,
        timeout_s=config.detect_timeout_s,
        actions=tuple(actions),
        nerd_details=tuple(nerd_details),
    )


def _poll_runtime(
    *,
    preferred_url: str | None,
    preferred_model: str | None,
    config: RuntimeBootstrapConfig,
    actions: tuple[str, ...],
    nerd_details: tuple[str, ...],
    require_model: bool,
) -> RuntimeStatus:
    for _ in range(config.poll_attempts):
        time.sleep(config.poll_interval_s)
        status = detect_runtime_status(
            preferred_url=preferred_url,
            preferred_model=preferred_model,
            timeout_s=config.detect_timeout_s,
            actions=actions,
            nerd_details=nerd_details,
        )
        if status.endpoint is None:
            continue
        if not require_model or status.model is not None:
            return status
    return detect_runtime_status(
        preferred_url=preferred_url,
        preferred_model=preferred_model,
        timeout_s=config.detect_timeout_s,
        actions=actions,
        nerd_details=nerd_details,
    )


def _launch_first_available(
    commands: tuple[tuple[str, ...], ...],
) -> str | None:
    for command in commands:
        launched = _launch_background_command(command)
        if launched is not None:
            return launched
    return None


def _pull_first_available(*, config: RuntimeBootstrapConfig, model: str) -> str | None:
    prefixes = (*config.ollama_pull_command_prefixes, config.ollama_pull_command_prefix)
    commands = tuple(prefix + (model,) for prefix in _dedupe_commands(prefixes))
    return _launch_first_available(commands)


def _dedupe_commands(
    commands: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    seen: set[tuple[str, ...]] = set()
    unique: list[tuple[str, ...]] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        unique.append(command)
    return tuple(unique)


def _launch_background_command(command: tuple[str, ...]) -> str | None:
    if not command or shutil.which(command[0]) is None:
        return None
    try:
        safe_command = validated_command(command)
    except ValueError:
        return None
    try:
        subprocess.Popen(
            safe_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    return "Started: " + " ".join(safe_command)
