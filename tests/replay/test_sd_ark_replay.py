"""Replay tests for deterministic SD-ARK behavior and fixtures."""

import asyncio
import json
from pathlib import Path

from ark.axioms import choose_action
from ark.forge_planner import ForgePlanner, build_planner_executor
from ark.mcp_containment import MCPExecutor, MCPRequest
from ark.sd_trisca import SVector, compute_trisca
from ark.task_graph import Executor, Scheduler, TaskSpec, chunk
from ark.tool_system import ToolRegistry, ToolSelector, ToolSpec

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real_world_sims.json"


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


def test_chunker_is_bounded_and_deterministic():
    chunks = chunk(tuple(range(7)), 3)

    assert chunks == [[0, 1, 2], [3, 4, 5], [6]]


def test_trisca_entropy_monotonicity():
    stable = compute_trisca([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    randomish = compute_trisca([0.1, 0.9, 0.2, 0.8, 0.3, 0.7])

    assert randomish.s.entropy > stable.s.entropy


def test_trisca_signal_isolation():
    pattern = compute_trisca([0.7, 0.7, 0.7, 0.7, 0.7, 0.7])
    noisy = compute_trisca([0.1, 0.8, 0.2, 0.9, 0.4, 0.6])

    assert pattern.s.signal_density > noisy.s.signal_density
    assert pattern.s.entropy < noisy.s.entropy


def test_trisca_efficiency_mapping():
    low_cost = compute_trisca([1, 1, 1, 1, 1, 1], output_value=100, cost_value=10)
    high_cost = compute_trisca([1, 1, 1, 1, 1, 1], output_value=100, cost_value=200)

    assert low_cost.s.efficiency > high_cost.s.efficiency


def test_trisca_inequality_spike():
    balanced = compute_trisca([1, 1, 1, 1, 1, 1])
    skewed = compute_trisca([10, 1, 1, 1, 1, 1])

    assert skewed.s.inequality > balanced.s.inequality


def test_trisca_stability_under_noise():
    baseline = compute_trisca([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    noisy = compute_trisca([0.5, 0.51, 0.49, 0.5, 0.5, 0.51])

    assert _distance(baseline.s, noisy.s) < 0.35


def test_trisca_temporal_weighting():
    newer = compute_trisca([1, 1, 1, 1, 1, 1], age_seconds=1)
    older = compute_trisca([1, 1, 1, 1, 1, 1], age_seconds=10)

    assert newer.s.temporal > older.s.temporal


def test_trisca_scaling_invariance():
    baseline = compute_trisca([1, 2, 3, 4, 5, 6])
    scaled = compute_trisca([10, 20, 30, 40, 50, 60])

    assert baseline.s == scaled.s


def test_trisca_small_delta_consistency():
    baseline = compute_trisca([1, 2, 3, 4, 5, 6])
    small_delta = compute_trisca([1, 2, 3.1, 4, 5, 6])

    assert _distance(baseline.s, small_delta.s) < 0.1


def test_trisca_orthogonality_fixture_is_not_degenerate():
    vectors = [
        SVector(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
        SVector(0.2, 0.5, 0.1, 0.6, 0.3, 0.4),
        SVector(0.6, 0.1, 0.5, 0.2, 0.4, 0.3),
        SVector(0.3, 0.6, 0.4, 0.1, 0.2, 0.5),
        SVector(0.5, 0.3, 0.6, 0.2, 0.1, 0.4),
        SVector(0.4, 0.6, 0.2, 0.5, 0.1, 0.3),
    ]

    assert max(abs(corr) for corr in _pairwise_correlations(vectors)) < 0.95


def test_real_world_fixture_actions_are_intuitive():
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    checked = 0

    for scenarios in fixtures.values():
        for scenario in scenarios:
            s = SVector(**scenario["s"])
            action = choose_action(s)
            assert action in scenario["expected_any"], scenario["id"]
            checked += 1

    assert checked == 6


def test_behavioral_integration_scenarios():
    scenarios = {
        "chaos": (SVector(0.4, 0.82, 0.3, 0.8, 0.35, 0.25), {"prune_noise", "reduce_load"}),
        "opportunity": (SVector(0.8, 0.2, 0.2, 0.9, 0.82, 0.85), {"scale_up"}),
        "waste": (SVector(0.5, 0.45, 0.4, 0.8, 0.3, 0.55), {"optimize_path"}),
        "imbalance": (SVector(0.5, 0.5, 0.8, 0.8, 0.45, 0.6), {"rebalance"}),
    }

    for name, (s, expected) in scenarios.items():
        assert choose_action(s) in expected, name


def _distance(left: SVector, right: SVector) -> float:
    return sum(abs(a - b) for a, b in zip(left.as_tuple(), right.as_tuple())) / 6


def _pairwise_correlations(vectors: list[SVector]) -> list[float]:
    columns = list(zip(*(vector.as_tuple() for vector in vectors)))
    correlations: list[float] = []
    for left_index in range(6):
        for right_index in range(left_index + 1, 6):
            correlations.append(_correlation(columns[left_index], columns[right_index]))
    return correlations


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_norm = sum((a - left_mean) ** 2 for a in left) ** 0.5
    right_norm = sum((b - right_mean) ** 2 for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
