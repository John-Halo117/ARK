"""Policy gate for Forge local MCP-style tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..runtime.config import DEFAULT_MCP_RUNTIME_CONFIG, McpRuntimeConfig
from .contracts import McpToolCall, McpToolSpec


@dataclass(frozen=True)
class McpPolicyDecision:
    allowed: bool
    reason: str
    error_code: str = ""
    context: dict[str, Any] | None = None


@dataclass(frozen=True)
class McpPolicyGate:
    config: McpRuntimeConfig = DEFAULT_MCP_RUNTIME_CONFIG

    def approve(self, call: McpToolCall, spec: McpToolSpec | None) -> McpPolicyDecision:
        if spec is None:
            return _deny(
                "MCP_UNKNOWN_TOOL", "tool is not registered", {"tool": call.name}
            )
        if call.caller not in self.config.allowed_callers:
            return _deny(
                "MCP_CALLER_BLOCKED", "caller is not allowed", {"caller": call.caller}
            )
        if call.name not in self.config.enabled_tools:
            return _deny(
                "MCP_TOOL_DISABLED", "tool is disabled by policy", {"tool": call.name}
            )
        missing = _missing_required(call.arguments, spec.input_schema)
        if missing:
            return _deny(
                "MCP_SCHEMA_REQUIRED",
                "required tool arguments are missing",
                {"missing": missing},
            )
        unknown = _unknown_arguments(call.arguments, spec.input_schema)
        if unknown:
            return _deny(
                "MCP_SCHEMA_UNKNOWN",
                "tool arguments are not in schema",
                {"unknown": unknown},
            )
        return McpPolicyDecision(
            True, "approved", context={"tool": call.name, "caller": call.caller}
        )


def _deny(error_code: str, reason: str, context: dict[str, Any]) -> McpPolicyDecision:
    return McpPolicyDecision(False, reason, error_code=error_code, context=context)


def _missing_required(arguments: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    if not isinstance(required, list):
        return []
    return [str(item) for item in required[:32] if str(item) not in arguments]


def _unknown_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if schema.get("additionalProperties", True):
        return []
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    allowed = set(str(item) for item in properties)
    return [key for key in arguments if key not in allowed][:32]
