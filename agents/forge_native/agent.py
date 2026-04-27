#!/usr/bin/env python3
"""Forge-native planner-only compatibility runtime for legacy agent wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ark.config import load_service_runtime_config
from ark.security import sanitize_string
from ark.time_utils import utc_now_iso


@dataclass(frozen=True)
class ForgeAgentProfile:
    name: str
    capabilities: tuple[str, ...]


PROFILE_CAPABILITIES: dict[str, ForgeAgentProfile] = {
    "opencode": ForgeAgentProfile(
        "opencode",
        (
            "code.analyze",
            "code.transform",
            "code.generate",
            "reasoning.plan",
            "reasoning.decompose",
        ),
    ),
    "openwolf": ForgeAgentProfile(
        "openwolf",
        ("anomaly.detect", "system.health", "metrics.ingest", "ashi.compute"),
    ),
    "composio": ForgeAgentProfile(
        "composio",
        (
            "external.web.fetch",
            "external.web.search",
            "external.maps.geocode",
            "external.maps.distance",
        ),
    ),
}

CAPABILITY_TO_TOOL: dict[str, str] = {
    "code.analyze": "tool.code.analyze",
    "code.transform": "tool.code.transform",
    "code.generate": "tool.code.generate",
    "reasoning.plan": "tool.reasoning.plan",
    "reasoning.decompose": "tool.reasoning.decompose",
    "anomaly.detect": "tool.stats.anomaly",
    "system.health": "tool.system.health",
    "metrics.ingest": "tool.metrics.ingest",
    "ashi.compute": "tool.trisca.compute",
    "external.web.fetch": "tool.data.fetch",
    "external.web.search": "tool.data.fetch",
    "external.maps.geocode": "tool.geo.geocode",
    "external.maps.distance": "tool.geo.distance",
}

MAX_ARG_FIELDS = 32
MAX_STRING_VALUE = 100_000


class ForgeNativeAgent:
    """Local-only Forge planner for legacy agent wrapper imports."""

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
        self.health = LocalHealth(self.service_name)
        self.health.register("local_runtime", lambda: True)

    async def handle_capability(
        self, capability: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        tool = CAPABILITY_TO_TOOL.get(capability)
        if tool is None or capability not in self.capabilities:
            return {"error": f"Unknown capability: {capability}"}
        return self._plan(capability, tool, params)

    async def analyze_code(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("code.analyze", "tool.code.analyze", params)

    async def transform_code(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("code.transform", "tool.code.transform", params)

    async def generate_code(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("code.generate", "tool.code.generate", params)

    async def plan(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("reasoning.plan", "tool.reasoning.plan", params)

    async def decompose(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("reasoning.decompose", "tool.reasoning.decompose", params)

    async def detect_anomaly(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("anomaly.detect", "tool.stats.anomaly", params)

    async def ingest_metric(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("metrics.ingest", "tool.metrics.ingest", params)

    async def compute_health(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("system.health", "tool.system.health", params)

    async def compute_ashi(self, _params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("ashi.compute", "tool.trisca.compute", _params)

    async def fetch_web(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("external.web.fetch", "tool.data.fetch", params)

    async def search_web(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("external.web.search", "tool.data.fetch", params)

    async def geocode(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("external.maps.geocode", "tool.geo.geocode", params)

    async def distance(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._plan("external.maps.distance", "tool.geo.distance", params)

    async def local_tool_placeholder(self, params: dict[str, Any]) -> dict[str, Any]:
        capability = sanitize_string(
            str(params.get("capability", "external.local")), 128
        )
        return self._failure(
            capability,
            "LOCAL_TOOL_MOVED_TO_FORGE",
            "Use Forge's local tool layer for this capability",
        )

    async def send_email(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.email", **params}
        )

    async def github_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.github", **params}
        )

    async def slack_message(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.slack", **params}
        )

    async def notion_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.notion", **params}
        )

    async def calendar_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.calendar", **params}
        )

    async def crm_action(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.local_tool_placeholder(
            {"capability": "external.crm", **params}
        )

    def _plan(self, capability: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": capability,
            "plans": [{"steps": [{"tool": tool, "args": _sanitize_args(args)}]}],
            "timestamp": utc_now_iso(),
        }

    def _failure(self, capability: str, code: str, reason: str) -> dict[str, Any]:
        return {
            "status": "error",
            "capability": capability,
            "error_code": code,
            "reason": reason,
            "context": {},
            "recoverable": True,
        }


def _sanitize_args(params: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in list(params.items())[:MAX_ARG_FIELDS]:
        clean_key = sanitize_string(str(key), 128)
        sanitized[clean_key] = _sanitize_value(value)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_string(value, MAX_STRING_VALUE)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, dict):
        return _sanitize_args(value)
    if isinstance(value, list | tuple):
        return [_sanitize_value(item) for item in list(value)[:MAX_ARG_FIELDS]]
    return sanitize_string(str(value), MAX_STRING_VALUE)


class LocalHealth:
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self._checks: dict[str, Any] = {}

    def register(self, name: str, check: Any) -> None:
        self._checks[name] = check

    def status(self) -> dict[str, bool]:
        return {name: bool(check()) for name, check in self._checks.items()}
