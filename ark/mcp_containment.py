"""MCP fallback containment for SD-ARK.

What: defines tool.mcp.exec as a sandboxed fallback boundary.
Why: MCP must never enter the core loop or expose global schemas.
Where: optional tool layer after API-first selection fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

MAX_MCP_PARAMS = 32


@dataclass(frozen=True)
class MCPRequest:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = "api_fallback"


@dataclass(frozen=True)
class MCPResult:
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ok":
            return {"status": "ok", "output": self.output}
        return {
            "status": "error",
            "error_code": self.error_code,
            "reason": self.reason,
            "context": {},
            "recoverable": True,
        }


class MCPExecutor:
    def __init__(self, allowed_tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]):
        self._allowed_tools = dict(allowed_tools)

    def exec(self, request: MCPRequest, *, api_failed: bool) -> MCPResult:
        if not api_failed:
            return MCPResult("error", error_code="MCP_NOT_FALLBACK", reason="mcp is fallback only")
        if request.tool != "tool.mcp.exec" and request.tool not in self._allowed_tools:
            return MCPResult("error", error_code="MCP_TOOL_DENIED", reason="mcp tool is not explicitly allowed")
        if len(request.params) > MAX_MCP_PARAMS:
            return MCPResult("error", error_code="MCP_PARAMS_TOO_LARGE", reason="mcp params exceed bound")
        handler = self._allowed_tools.get(request.tool)
        if handler is None:
            return MCPResult("error", error_code="MCP_TOOL_MISSING", reason="mcp fallback handler is missing")
        try:
            return MCPResult("ok", output=handler(dict(request.params)))
        except Exception as exc:
            return MCPResult("error", error_code="MCP_EXEC_FAILED", reason=str(exc))
