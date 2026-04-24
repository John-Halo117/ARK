#!/usr/bin/env python3
"""Forge-native local compatibility runtime for legacy agent wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ark.config import load_service_runtime_config
from ark.math_utils import zscore_anomaly
from ark.security import sanitize_string
from ark.time_utils import utc_now_iso


@dataclass(frozen=True)
class ForgeAgentProfile:
    name: str
    capabilities: tuple[str, ...]


PROFILE_CAPABILITIES: dict[str, ForgeAgentProfile] = {
    "opencode": ForgeAgentProfile(
        "opencode",
        ("code.analyze", "code.transform", "code.generate", "reasoning.plan", "reasoning.decompose"),
    ),
    "openwolf": ForgeAgentProfile(
        "openwolf",
        ("anomaly.detect", "system.health", "metrics.ingest", "ashi.compute"),
    ),
    "composio": ForgeAgentProfile(
        "composio",
        ("external.web.fetch", "external.web.search", "external.maps.geocode", "external.maps.distance"),
    ),
}


class ForgeNativeAgent:
    """Local-only Forge replacement for the deleted Aider agent runtime."""

    def __init__(self, profile: str) -> None:
        selected = PROFILE_CAPABILITIES.get(profile)
        if selected is None:
            raise ValueError(f"Unsupported Forge agent profile: {profile}")
        runtime = load_service_runtime_config()
        self.service_name = selected.name
        self.capabilities = list(selected.capabilities)
        self.instance_id = runtime.instance_id
        self.nats_url = runtime.nats_url
        self.request_count = 0
        self.metric_history: dict[str, list[float]] = {}
        self._max_metric_history = 100
        self.ashi_score = 100
        self.health = LocalHealth(self.service_name)
        self.health.register("local_runtime", lambda: True)

    async def handle_capability(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "code.analyze": self.analyze_code,
            "code.transform": self.transform_code,
            "code.generate": self.generate_code,
            "reasoning.plan": self.plan,
            "reasoning.decompose": self.decompose,
            "anomaly.detect": self.detect_anomaly,
            "system.health": self.compute_health,
            "metrics.ingest": self.ingest_metric,
            "ashi.compute": self.compute_ashi,
            "external.web.fetch": self.local_tool_placeholder,
            "external.web.search": self.local_tool_placeholder,
            "external.maps.geocode": self.local_tool_placeholder,
            "external.maps.distance": self.local_tool_placeholder,
        }
        handler = handlers.get(capability)
        if handler is None:
            return {"error": f"Unknown capability: {capability}"}
        return await handler(params)

    async def analyze_code(self, params: dict[str, Any]) -> dict[str, Any]:
        source = sanitize_string(str(params.get("source", "")), 100_000)
        language = sanitize_string(str(params.get("language", "python")), 32)
        return self._result("code.analyze", {"language": language, "analysis": {"lines": len(source.split("\n")), "chars": len(source)}})

    async def transform_code(self, params: dict[str, Any]) -> dict[str, Any]:
        source = sanitize_string(str(params.get("source", "")), 100_000)
        transform_type = sanitize_string(str(params.get("type", "refactor")), 64)
        return self._result("code.transform", {"type": transform_type, "output": source})

    async def generate_code(self, params: dict[str, Any]) -> dict[str, Any]:
        spec = sanitize_string(str(params.get("spec", "")), 8192)
        language = sanitize_string(str(params.get("language", "python")), 32)
        return self._result("code.generate", {"language": language, "spec": spec})

    async def plan(self, params: dict[str, Any]) -> dict[str, Any]:
        goal = sanitize_string(str(params.get("goal", "")), 512)
        return self._result("reasoning.plan", {"goal": goal, "plan": {"steps": ["inspect", "edit", "verify", "review"]}})

    async def decompose(self, params: dict[str, Any]) -> dict[str, Any]:
        problem = sanitize_string(str(params.get("problem", "")), 512)
        return self._result("reasoning.decompose", {"problem": problem, "subtasks": ["find scope", "patch", "test"]})

    async def check_anomaly(self, metric: str, value: float) -> bool:
        history = self.metric_history.get(metric, [])
        return zscore_anomaly(history, value, max_samples=self._max_metric_history)

    async def detect_anomaly(self, params: dict[str, Any]) -> dict[str, Any]:
        metric = sanitize_string(str(params.get("metric", "unknown")), 128)
        value = float(params.get("value", 0))
        is_anomaly = await self.check_anomaly(metric, value)
        return self._result("anomaly.detect", {"metric": metric, "value": value, "is_anomaly": is_anomaly, "severity": "high" if is_anomaly else "normal"})

    async def ingest_metric(self, params: dict[str, Any]) -> dict[str, Any]:
        metric = sanitize_string(str(params.get("name", "unknown")), 128)
        value = float(params.get("value", 0))
        self.metric_history.setdefault(metric, []).append(value)
        self.metric_history[metric] = self.metric_history[metric][-self._max_metric_history :]
        return self._result("metrics.ingest", {"metric": metric, "samples": len(self.metric_history[metric])})

    async def compute_health(self, params: dict[str, Any]) -> dict[str, Any]:
        metrics = params.get("metrics", {})
        anomalies = await self._count_anomalies(metrics if isinstance(metrics, dict) else {})
        health_score = max(0, 100 - anomalies * 20)
        status = "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "critical"
        return self._result("system.health", {"health_score": health_score, "status": status, "anomalies": anomalies})

    async def compute_ashi(self, _params: dict[str, Any]) -> dict[str, Any]:
        latest = {metric: values[-1] for metric, values in self.metric_history.items() if values}
        anomalies = await self._count_anomalies(latest)
        self.ashi_score = max(0, 100 - anomalies * 15)
        return self._result("ashi.compute", {"ashi_score": self.ashi_score, "level": _ashi_level(self.ashi_score)})

    async def local_tool_placeholder(self, params: dict[str, Any]) -> dict[str, Any]:
        capability = sanitize_string(str(params.get("capability", "external.local")), 128)
        return self._failure(capability, "LOCAL_TOOL_MOVED_TO_FORGE", "Use Forge's local tool layer for this capability")

    async def send_email(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.email", **params})

    async def github_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.github", **params})

    async def slack_message(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.slack", **params})

    async def notion_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.notion", **params})

    async def calendar_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.calendar", **params})

    async def crm_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder({"capability": "external.crm", **params})

    async def _count_anomalies(self, metrics: dict[str, Any]) -> int:
        count = 0
        for metric, value in list(metrics.items())[:32]:
            if await self.check_anomaly(sanitize_string(str(metric), 128), float(value)):
                count += 1
        return count

    def _result(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"agent": self.service_name, "instance_id": self.instance_id, "capability": capability, **payload, "timestamp": utc_now_iso()}

    def _failure(self, capability: str, code: str, reason: str) -> dict[str, Any]:
        return {"status": "error", "capability": capability, "error_code": code, "reason": reason, "context": {}, "recoverable": True}


def _ashi_level(score: int) -> str:
    if score >= 90:
        return "optimal"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    return "critical"


class LocalHealth:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self._checks: dict[str, Any] = {}

    def register(self, name: str, check: Any) -> None:
        self._checks[name] = check

    def status(self) -> dict[str, bool]:
        return {name: bool(check()) for name, check in self._checks.items()}
