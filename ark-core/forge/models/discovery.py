"""Discovery helpers for low-friction Ollama usage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from urllib import request

from ..exec.runner import validated_command


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def detect_ollama_endpoint(
    *,
    preferred_url: str | None = None,
    timeout_s: int = 5,
) -> tuple[str | None, list[str]]:
    """Return the first reachable Ollama URL and its installed models."""

    for base_url in candidate_ollama_urls(preferred_url):
        try:
            payload = _fetch_tags(base_url, timeout_s=timeout_s)
        except OSError:
            continue
        models = [
            str(item.get("name"))
            for item in payload.get("models", [])
            if item.get("name")
        ]
        return base_url, models
    return None, []


def candidate_ollama_urls(preferred_url: str | None = None) -> list[str]:
    """Build an ordered list of likely Ollama endpoints."""

    candidates: list[str] = []
    for item in (
        preferred_url,
        os.getenv("FORGE_OLLAMA_URL"),
        DEFAULT_OLLAMA_URL,
        *[f"http://{host}:11434/api/generate" for host in _wsl_host_candidates()],
    ):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def choose_model(models: list[str], preferred: str | None = None) -> str | None:
    """Pick the most coding-friendly installed model."""

    if preferred and preferred in models:
        return preferred
    if not models:
        return None
    ranked = sorted(models, key=_model_rank)
    return ranked[0]


def compact_runtime_summary(
    base_url: str | None, model: str | None, models: list[str]
) -> str:
    """Render a short human-readable runtime summary."""

    if base_url is None:
        return "Ollama not detected"
    if model is None:
        return f"Ollama at {base_url} (models: {', '.join(models) or 'none'})"
    return f"Ollama at {base_url} using {model}"


def _fetch_tags(base_url: str, *, timeout_s: int) -> dict[str, object]:
    tags_url = _tags_endpoint(base_url)
    with request.urlopen(tags_url, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _tags_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/api/generate"):
        return root[: -len("/api/generate")] + "/api/tags"
    if root.endswith("/generate"):
        return root[: -len("/generate")] + "/tags"
    return root + "/tags"


def _wsl_host_candidates() -> list[str]:
    candidates: list[str] = []
    route_host = _default_gateway()
    if route_host:
        candidates.append(route_host)
    nameserver = _resolv_nameserver()
    if nameserver and nameserver not in candidates:
        candidates.append(nameserver)
    return candidates


def _default_gateway() -> str | None:
    try:
        command = validated_command(["ip", "route"])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("default via "):
            parts = line.split()
            if len(parts) >= 3:
                return parts[2]
    return None


def _resolv_nameserver() -> str | None:
    path = Path("/etc/resolv.conf")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("nameserver "):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def _model_rank(name: str) -> tuple[int, int, str]:
    lower = name.lower()
    family_rank = 50
    if "qwen3-coder" in lower:
        family_rank = 0
    elif "qwen2.5-coder" in lower:
        family_rank = 10
    elif "deepseek-coder" in lower:
        family_rank = 20
    elif "codellama" in lower:
        family_rank = 30
    elif "coder" in lower or "code" in lower:
        family_rank = 40
    size_penalty = (
        0 if any(tag in lower for tag in ("7b", "8b", "14b", "30b", "32b")) else 1
    )
    return (family_rank, size_penalty, lower)
