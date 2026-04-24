"""Forge runtime bootstrap checks."""

from __future__ import annotations

from forge.runtime import bootstrap
from forge.runtime.config import RuntimeBootstrapConfig


def test_detect_runtime_status_reports_ready(monkeypatch: object) -> None:
    monkeypatch.setattr(
        bootstrap,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )

    status = bootstrap.detect_runtime_status()

    assert status.ready is True
    assert status.phase == "ready"
    assert status.model == "qwen3-coder:30b"


def test_ensure_runtime_ready_starts_service_and_model(monkeypatch: object) -> None:
    responses = iter(
        [
            (None, []),
            ("http://127.0.0.1:11434/api/generate", []),
            ("http://127.0.0.1:11434/api/generate", ["qwen2.5-coder:7b"]),
            ("http://127.0.0.1:11434/api/generate", ["qwen2.5-coder:7b"]),
        ]
    )
    launched: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        bootstrap,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: next(responses),
    )
    monkeypatch.setattr(bootstrap.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        bootstrap,
        "_launch_background_command",
        lambda command: launched.append(command) or f"Started: {' '.join(command)}",
    )

    status = bootstrap.ensure_runtime_ready(
        config=RuntimeBootstrapConfig(
            poll_attempts=2,
            poll_interval_s=0.0,
            ollama_start_commands=(("ollama", "serve"),),
            bootstrap_model="qwen2.5-coder:7b",
        )
    )

    assert status.ready is True
    assert launched == [
        ("ollama", "serve"),
        ("ollama", "pull", "qwen2.5-coder:7b"),
    ]
    assert status.actions == (
        "Forge started the local AI service in the background.",
        "Forge is downloading qwen2.5-coder:7b in the background.",
    )
