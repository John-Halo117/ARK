"""Central Forge MCP registry with a strict local policy gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..runtime.config import DEFAULT_MCP_RUNTIME_CONFIG, McpRuntimeConfig
from .contracts import McpTool, McpToolCall, mcp_failure
from .policy import McpPolicyGate
from .tools import DockerStatusTool, MapsDistanceTool, RepoFilesTool


@dataclass(frozen=True)
class McpRegistry:
    tools: dict[str, McpTool]
    policy_gate: McpPolicyGate

    def specs(self) -> list[dict[str, object]]:
        return [tool.spec.as_dict() for tool in self.tools.values()]

    def execute(self, call: McpToolCall) -> dict[str, object]:
        tool = self.tools.get(call.name)
        decision = self.policy_gate.approve(call, tool.spec if tool else None)
        if not decision.allowed:
            return mcp_failure(
                call.name,
                decision.error_code,
                decision.reason,
                context=decision.context,
            ).as_dict()
        return tool.execute(call).as_dict() if tool else {}


def build_default_mcp_registry(
    repo_root: Path,
    *,
    config: McpRuntimeConfig = DEFAULT_MCP_RUNTIME_CONFIG,
) -> McpRegistry:
    tools: tuple[McpTool, ...] = (
        DockerStatusTool(repo_root, config),
        RepoFilesTool(repo_root, config),
        MapsDistanceTool(config),
    )
    selected = {tool.spec.name: tool for tool in tools[: config.max_tools]}
    return McpRegistry(tools=selected, policy_gate=McpPolicyGate(config))
