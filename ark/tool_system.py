"""TRISCA-driven tool registry and selector.

What: scores registered API tools by capability vector, cost, and success rate.
Why: expose at most five tools and prefer API tools before MCP fallback.
Where: used by skills and optional planners outside the Go core loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Sequence

from ark.sd_trisca import SVector

MAX_TOOLS = 128
MAX_EXPOSED_TOOLS = 5
VECTOR_SIZE = 6


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str
    capability_vector: tuple[float, float, float, float, float, float]
    cost: float
    success_rate: float
    kind: str = "api"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[ToolSpec, ...]

    def __post_init__(self) -> None:
        if len(self.tools) > MAX_TOOLS:
            raise ValueError(f"tool count exceeds bound: {MAX_TOOLS}")
        for index in range(min(len(self.tools), MAX_TOOLS)):
            tool = self.tools[index]
            if not tool.name or not tool.capability:
                raise ValueError(f"tool {index} requires name and capability")
            if len(tool.capability_vector) != VECTOR_SIZE:
                raise ValueError(f"tool {tool.name} requires S[6] vector")

    def by_capability(self, capability: str) -> tuple[ToolSpec, ...]:
        matches = [tool for tool in self.tools if tool.capability == capability or capability == "*"]
        return tuple(matches[:MAX_TOOLS])


class ToolSelector:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def select(self, s: SVector, capability: str = "*", *, allow_mcp: bool = False) -> tuple[ToolSpec, ...]:
        candidates = self._registry.by_capability(capability)
        scored: list[tuple[float, str, ToolSpec]] = []
        target = s.as_tuple()
        for index in range(min(len(candidates), MAX_TOOLS)):
            tool = candidates[index]
            if tool.kind == "mcp" and not allow_mcp:
                continue
            score = _similarity(target, tool.capability_vector) * tool.success_rate - tool.cost
            if tool.kind == "mcp":
                score -= 0.25
            scored.append((score, tool.name, tool))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in scored[:MAX_EXPOSED_TOOLS])


def _similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for index in range(VECTOR_SIZE):
        dot += left[index] * right[index]
        left_norm += left[index] * left[index]
        right_norm += right[index] * right[index]
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (sqrt(left_norm) * sqrt(right_norm))
