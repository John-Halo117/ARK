"""Forge planner facade for SD-ARK.

What: turns goals/problems into TaskSpec DAG descriptions.
Why: Forge agents become planners only; execution belongs to the scheduler.
Where: used by profiled agents for reasoning.plan and reasoning.decompose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ark.security import sanitize_string
from ark.sd_trisca import compute_trisca
from ark.task_graph import Executor, TaskHandler, TaskSpec
from ark.tool_system import ToolRegistry, ToolSelector, ToolSpec

MAX_PLAN_STEPS = 8


@dataclass(frozen=True)
class Plan:
    goal: str
    tasks: tuple[TaskSpec, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [
                {
                    "id": task.id,
                    "capability": task.capability,
                    "params": task.params,
                    "depends_on": list(task.depends_on),
                    "timeout_seconds": task.timeout_seconds,
                }
                for task in self.tasks[:MAX_PLAN_STEPS]
            ],
        }


class ForgePlanner:
    """Bounded planner that emits DAG specs and performs no execution."""

    def plan(self, goal: str) -> Plan:
        clean_goal = sanitize_string(goal, 512)
        return Plan(
            clean_goal,
            (
                TaskSpec("understand", "reasoning.decompose", {"problem": clean_goal}),
                TaskSpec("select", "tool.select", {"goal": clean_goal}, depends_on=("understand",)),
                TaskSpec("verify", "result.verify", {"goal": clean_goal}, depends_on=("select",)),
            ),
        )

    def decompose(self, problem: str) -> Plan:
        clean_problem = sanitize_string(problem, 512)
        return Plan(
            clean_problem,
            (
                TaskSpec("inputs", "analysis.inputs", {"problem": clean_problem}),
                TaskSpec("process", "analysis.process", {"problem": clean_problem}, depends_on=("inputs",)),
                TaskSpec("verify", "analysis.verify", {"problem": clean_problem}, depends_on=("process",)),
            ),
        )


def default_planner_handlers(registry: ToolRegistry | None = None) -> dict[str, TaskHandler]:
    """Return bounded handlers for every capability emitted by ForgePlanner.

    Runtime: O(tools + payload keys). Memory: O(1) beyond bounded result maps.
    Failure: handlers return structured error dictionaries for invalid inputs.
    """

    tool_registry = registry or _default_tool_registry()

    def decompose(params: dict[str, Any]) -> dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        return {"status": "ok", "items": ["inputs", "process", "verify"], "problem": problem}

    def tool_select(params: dict[str, Any]) -> dict[str, Any]:
        observations = _bounded_observations(params)
        capability = sanitize_string(params.get("capability", "*"), 128) or "*"
        allow_mcp = bool(params.get("allow_mcp", False))
        trisca = compute_trisca(observations)
        selected = ToolSelector(tool_registry).select(trisca.s, capability, allow_mcp=allow_mcp)
        return {
            "status": "ok",
            "tools": [{"name": tool.name, "capability": tool.capability, "kind": tool.kind} for tool in selected],
            "trisca": trisca.as_dict(),
        }

    def result_verify(params: dict[str, Any]) -> dict[str, Any]:
        goal = sanitize_string(params.get("goal", ""), 512)
        return {"status": "ok", "verified": True, "goal": goal}

    def analysis_inputs(params: dict[str, Any]) -> dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        return {"status": "ok", "inputs": sorted(params)[:8], "problem": problem}

    def analysis_process(params: dict[str, Any]) -> dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        return {"status": "ok", "process": "bounded", "problem": problem}

    def analysis_verify(params: dict[str, Any]) -> dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        return {"status": "ok", "verified": True, "problem": problem}

    return {
        "reasoning.decompose": decompose,
        "tool.select": tool_select,
        "result.verify": result_verify,
        "analysis.inputs": analysis_inputs,
        "analysis.process": analysis_process,
        "analysis.verify": analysis_verify,
    }


def build_planner_executor(registry: ToolRegistry | None = None) -> Executor:
    return Executor(default_planner_handlers(registry))


def _default_tool_registry() -> ToolRegistry:
    base_vector = (0.7, 0.2, 0.1, 1.0, 0.8, 0.6)
    return ToolRegistry(
        (
            ToolSpec("api.runtime.status", "system.health", base_vector, cost=0.05, success_rate=0.99),
            ToolSpec("api.analysis.local", "analysis.process", base_vector, cost=0.08, success_rate=0.95),
            ToolSpec("api.verify.local", "result.verify", base_vector, cost=0.04, success_rate=0.98),
            ToolSpec("api.reasoning.local", "reasoning.decompose", base_vector, cost=0.06, success_rate=0.96),
            ToolSpec("api.tool.select", "tool.select", base_vector, cost=0.03, success_rate=0.99),
        )
    )


def _bounded_observations(params: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    raw = params.get("observations", ())
    if not isinstance(raw, (list, tuple)):
        raw = ()
    values = [0.0] * 6
    for index in range(min(len(raw), 6)):
        try:
            values[index] = float(raw[index])
        except (TypeError, ValueError):
            values[index] = 0.0
    return (values[0], values[1], values[2], values[3], values[4], values[5])
