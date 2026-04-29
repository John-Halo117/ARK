"""Replay tests for deterministic SD-ARK Python execution helpers."""

import asyncio

from ark.mcp_containment import MCPExecutor, MCPRequest
from ark.forge_planner import ForgePlanner, build_planner_executor
from ark.sd_trisca import compute_trisca
from ark.task_graph import Executor, Scheduler, TaskSpec
from ark.tool_system import ToolRegistry, ToolSelector, ToolSpec


def test_trisca_is_deterministic():
    observations = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]

    first = compute_trisca(observations, age_seconds=0)
    second = compute_trisca(observations, age_seconds=0)

    assert first == second
    assert len(first.trace) == 6


def test_tool_selector_caps_exposure_and_prefers_api():
    trisca = compute_trisca([0.8, 0.7, 0.6, 0.5, 0.4, 0.3])
    registry = ToolRegistry(
        tuple(
            ToolSpec(
                name=f"api-{index}",
                capability="demo.run",
                capability_vector=trisca.s.as_tuple(),
                cost=0.01 * index,
                success_rate=0.99,
            )
            for index in range(8)
        )
        + (
            ToolSpec(
                name="mcp-fallback",
                capability="demo.run",
                capability_vector=trisca.s.as_tuple(),
                cost=0,
                success_rate=1,
                kind="mcp",
            ),
        )
    )

    selected = ToolSelector(registry).select(trisca.s, "demo.run")

    assert len(selected) == 5
    assert all(tool.kind == "api" for tool in selected)


def test_dag_scheduler_replays_idempotent_results():
    calls = {"count": 0}

    def handler(params):
        calls["count"] += 1
        return {"status": "ok", "value": params["value"]}

    executor = Executor({"demo.run": handler})
    scheduler = Scheduler(executor)
    tasks = (TaskSpec("a", "demo.run", {"value": 1}), TaskSpec("b", "demo.run", {"value": 2}, depends_on=("a",)))

    first = asyncio.run(scheduler.run(tasks))
    second = asyncio.run(scheduler.run(tasks))

    assert [result.status for result in first] == ["ok", "ok"]
    assert [result.status for result in second] == ["ok", "ok"]
    assert calls["count"] == 2


def test_mcp_is_fallback_only():
    executor = MCPExecutor({"tool.mcp.exec": lambda params: {"echo": params["value"]}})

    denied = executor.exec(MCPRequest("tool.mcp.exec", {"value": 1}), api_failed=False)
    allowed = executor.exec(MCPRequest("tool.mcp.exec", {"value": 1}), api_failed=True)

    assert denied.status == "error"
    assert denied.error_code == "MCP_NOT_FALLBACK"
    assert allowed.status == "ok"


def test_forge_planner_emitted_capabilities_have_handlers():
    planner = ForgePlanner()
    executor = build_planner_executor()
    scheduler = Scheduler(executor)

    results = asyncio.run(scheduler.run(planner.plan("ship sd-ark").tasks))

    assert [result.status for result in results] == ["ok", "ok", "ok"]


def test_dag_scheduler_blocks_dependents_after_failed_dependency():
    def ok_handler(_params):
        return {"status": "ok"}

    executor = Executor({"demo.ok": ok_handler})
    scheduler = Scheduler(executor)
    tasks = (
        TaskSpec("a", "missing.handler"),
        TaskSpec("b", "demo.ok", depends_on=("a",)),
    )

    results = asyncio.run(scheduler.run(tasks))

    assert results[0].task_id == "a"
    assert results[0].status == "error"
    assert results[1].task_id == "scheduler"
    assert results[1].error_code == "DAG_UNRESOLVED"
