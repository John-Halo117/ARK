"""Thin Ollama HTTP client used by Forge."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from threading import Lock
from urllib import error, request

from ..runtime.guards import require_unified_diff
from ..types import ContextBundle
from .prompts import build_attack_prompt, build_diff_prompt, build_plan_prompt


class OllamaError(RuntimeError):
    """Raised when the Ollama runtime cannot satisfy a Forge request."""


@dataclass(frozen=True)
class OllamaConfig:
    """Runtime configuration for the Ollama adapter."""

    enabled: bool = False
    required: bool = False
    planner_enabled: bool = True
    redteam_enabled: bool = True
    base_url: str = "http://127.0.0.1:11434/api/generate"
    executor_model: str = "qwen2.5-coder:7b"
    planner_model: str = "qwen2.5-coder:14b"
    redteam_model: str = "qwen2.5-coder:7b"
    timeout_s: int = 120
    num_ctx: int = 4096
    temperature: float = 0.2
    top_p: float = 0.9
    base_seed: int = 0

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        """Load config from environment variables."""

        enabled = os.getenv("FORGE_ENABLE_OLLAMA", "0") == "1"
        required = os.getenv("FORGE_OLLAMA_REQUIRED", "0") == "1"
        planner_enabled = os.getenv("FORGE_OLLAMA_PLANNER", "1") == "1"
        redteam_enabled = os.getenv("FORGE_OLLAMA_REDTEAM", "1") == "1"
        base_url = os.getenv("FORGE_OLLAMA_URL", cls.base_url)
        executor = os.getenv("FORGE_EXECUTOR_MODEL", cls.executor_model)
        planner = os.getenv("FORGE_PLANNER_MODEL", "qwen2.5-coder:14b")
        redteam = os.getenv("FORGE_REDTEAM_MODEL", executor)
        timeout_s = int(os.getenv("FORGE_OLLAMA_TIMEOUT", str(cls.timeout_s)))
        num_ctx = int(os.getenv("FORGE_OLLAMA_NUM_CTX", str(cls.num_ctx)))
        temperature = float(os.getenv("FORGE_OLLAMA_TEMPERATURE", str(cls.temperature)))
        top_p = float(os.getenv("FORGE_OLLAMA_TOP_P", str(cls.top_p)))
        base_seed = int(os.getenv("FORGE_OLLAMA_SEED", str(cls.base_seed)))
        return cls(
            enabled=enabled,
            required=required,
            planner_enabled=planner_enabled,
            redteam_enabled=redteam_enabled,
            base_url=base_url,
            executor_model=executor,
            planner_model=planner,
            redteam_model=redteam,
            timeout_s=timeout_s,
            num_ctx=num_ctx,
            temperature=temperature,
            top_p=top_p,
            base_seed=base_seed,
        )


class OllamaClient:
    """Optional model adapter. Forge keeps correctness authority in code."""

    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig.from_env()
        self._lock = Lock()
        self._status_cache: dict[str, object] | None = None

    @property
    def enabled(self) -> bool:
        """Return whether model calls are enabled."""

        return self.config.enabled

    def diff(self, context: ContextBundle, seed: int = 0) -> str | None:
        """Generate one unified diff candidate when Ollama is enabled."""

        if not self.enabled:
            return None
        prompt = build_diff_prompt(context)
        return require_unified_diff(
            self._call(
                self.config.executor_model,
                prompt,
                seed=self.config.base_seed + seed,
            )
        )

    def plan(self, context: ContextBundle) -> dict[str, object] | None:
        """Generate a bounded plan when the planner is enabled."""

        if not self.enabled or not self.config.planner_enabled:
            return None
        response = self._call(
            self.config.planner_model,
            build_plan_prompt(context),
            format_json=True,
        )
        return _extract_json(response)

    def critique(
        self, context: ContextBundle, delta: str, mode: str
    ) -> dict[str, object] | None:
        """Generate an adversarial critique."""

        if not self.enabled or not self.config.redteam_enabled:
            return None
        seed = self.config.base_seed + abs(hash(mode)) % 10_000
        response = self._call(
            self.config.redteam_model,
            build_attack_prompt(context, delta, mode),
            seed=seed,
            format_json=True,
        )
        return _extract_json(response)

    def check(self, *, refresh: bool = False) -> dict[str, object]:
        """Probe the local Ollama runtime and cache the result."""

        if self._status_cache is not None and not refresh:
            return dict(self._status_cache)
        status = self._probe()
        self._status_cache = dict(status)
        return dict(status)

    def require_ready(self) -> dict[str, object]:
        """Ensure a usable Ollama runtime exists."""

        status = self.check()
        if not self.enabled:
            return status
        if not status["reachable"]:
            raise OllamaError(str(status["error"]))
        required_models = {
            self.config.executor_model,
        }
        if self.config.planner_enabled:
            required_models.add(self.config.planner_model)
        if self.config.redteam_enabled:
            required_models.add(self.config.redteam_model)
        missing = sorted(required_models - set(status["models"]))
        if missing:
            raise OllamaError(
                f"Ollama is reachable but missing required models: {', '.join(missing)}"
            )
        return status

    def as_dict(self) -> dict[str, object]:
        """Expose effective runtime configuration for logs and results."""

        payload = asdict(self.config)
        payload["reachable"] = bool((self._status_cache or {}).get("reachable"))
        return payload

    def _call(
        self,
        model: str,
        prompt: str,
        *,
        seed: int = 0,
        format_json: bool = False,
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "num_ctx": self.config.num_ctx,
                "seed": seed,
            },
        }
        if format_json:
            payload["format"] = "json"
        req = request.Request(
            self.config.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._lock:
                with request.urlopen(req, timeout=self.config.timeout_s) as response:
                    body = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, error.URLError) as exc:
            raise OllamaError(
                f"failed to reach Ollama at {self.config.base_url}: {exc}"
            ) from exc
        if "response" not in body:
            raise OllamaError("Ollama response missing `response` field")
        return str(body["response"])

    def _probe(self) -> dict[str, object]:
        tags_url = _tags_endpoint(self.config.base_url)
        if not self.enabled:
            return {
                "enabled": False,
                "required": self.config.required,
                "reachable": False,
                "models": [],
                "base_url": self.config.base_url,
                "error": None,
            }
        try:
            with self._lock:
                with request.urlopen(
                    tags_url, timeout=min(self.config.timeout_s, 10)
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, error.URLError) as exc:
            return {
                "enabled": True,
                "required": self.config.required,
                "reachable": False,
                "models": [],
                "base_url": self.config.base_url,
                "error": f"failed to reach Ollama at {tags_url}: {exc}",
            }
        models = [
            str(item.get("name"))
            for item in payload.get("models", [])
            if item.get("name")
        ]
        return {
            "enabled": True,
            "required": self.config.required,
            "reachable": True,
            "models": models,
            "base_url": self.config.base_url,
            "error": None,
        }


def _extract_json(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1].strip() if len(parts) >= 3 else cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < 0 or end < start:
        raise ValueError("model response did not contain JSON")
    return json.loads(cleaned[start : end + 1])


def _tags_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/api/generate"):
        return root[: -len("/api/generate")] + "/api/tags"
    if root.endswith("/generate"):
        return root[: -len("/generate")] + "/tags"
    return root + "/tags"
