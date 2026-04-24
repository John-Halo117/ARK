"""Strict contracts for Forge local MCP-style tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    timeout_s: int
    max_output_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "timeout_s": self.timeout_s,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True)
class McpToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    caller: str = "ollama"
    trace_id: str = ""


@dataclass(frozen=True)
class McpToolResult:
    status: str
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ok":
            return {"status": "ok", "tool": self.tool, **self.data}
        return {
            "status": "error",
            "tool": self.tool,
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


class McpTool(Protocol):
    spec: McpToolSpec

    def execute(self, call: McpToolCall) -> McpToolResult: ...


def mcp_success(tool: str, data: dict[str, Any]) -> McpToolResult:
    return McpToolResult(status="ok", tool=tool, data=data, recoverable=False)


def mcp_failure(
    tool: str,
    error_code: str,
    reason: str,
    *,
    context: dict[str, Any] | None = None,
    recoverable: bool = True,
) -> McpToolResult:
    return McpToolResult(
        status="error",
        tool=tool,
        error_code=error_code,
        reason=reason,
        context=context or {},
        recoverable=recoverable,
    )
