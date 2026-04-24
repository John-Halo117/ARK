"""Bounded Forge task loop."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..context.provider import ContextProvider, DefaultContextProvider
from ..control.controller import mode_from_phi, need_planner
from ..control.phi import compute_phi
from ..runtime.config import DEFAULT_POLICY_CONFIG
from ..runtime.guards import ensure_iteration_budget
from ..runtime.logs import task_metrics
from ..types import EvaluationResult, ForgeState, ForgeTask, TaskExecution, TaskResult
from ..verify.eval import evaluate_candidate, passes_contract, register_failure
from ..verify.adapters import PythonVerifierAdapter, VerifierAdapter
from ..transform.propose import propose_deltas


def run_task(
    task: ForgeTask,
    repo_root,
    state: ForgeState,
    banlist,
    client,
    *,
    tool_root,
    dry_run: bool,
    mode_override=None,
    context_provider: ContextProvider | None = None,
    verifier: VerifierAdapter | None = None,
    risk_threshold: float = DEFAULT_POLICY_CONFIG.risk_threshold,
    event_sink: object | None = None,
) -> TaskExecution:
    """Execute one bounded Forge pass."""

    context_provider_impl = context_provider or DefaultContextProvider()
    verifier_impl = verifier or PythonVerifierAdapter()
    ensure_iteration_budget(0)
    context, pre_phi, repeated, mode = _prepare_context_and_control(
        task,
        repo_root,
        state,
        banlist,
        context_provider=context_provider_impl,
        mode_override=mode_override,
        event_sink=event_sink,
    )
    context = _maybe_apply_plan(
        task,
        context,
        state,
        repeated,
        pre_phi,
        client=client,
        context_provider=context_provider_impl,
        event_sink=event_sink,
    )
    if dry_run:
        return _dry_run_execution(task, state, pre_phi, mode, repeated)
    baseline = _measure_baseline(task, repo_root, tool_root, verifier_impl, event_sink)
    candidates = propose_deltas(context, mode, client=client, event_sink=event_sink)
    if not candidates:
        return _manual_review_execution(
            task, state, pre_phi, mode, repeated, "no delta candidates were produced"
        )
    _emit_candidates_generated(task, candidates, event_sink)
    evaluations = _evaluate(
        context,
        candidates,
        banlist,
        state.attempt,
        repo_root,
        tool_root,
        baseline,
        client,
        verifier=verifier_impl,
        risk_threshold=risk_threshold,
        event_sink=event_sink,
    )
    return _finalize_execution(
        task,
        state,
        banlist,
        context,
        candidates,
        evaluations,
        repeated,
        mode,
        risk_threshold=risk_threshold,
        event_sink=event_sink,
    )


def _prepare_context_and_control(
    task: ForgeTask,
    repo_root,
    state: ForgeState,
    banlist,
    *,
    context_provider: ContextProvider,
    mode_override,
    event_sink: object | None,
):
    _emit(
        event_sink,
        "context",
        f"building context for {task.identifier}",
        task_id=task.identifier,
        context_level=task.context_level,
        test_mode=task.test_mode,
    )
    context = context_provider.build(repo_root, task, banlist, state)
    repeated = banlist.repeat_pressure(state.attempt)
    phi = compute_phi(
        state.evaluations,
        missing_context=context.missing_context,
        repeated_failures=repeated,
    )
    mode = mode_override or mode_from_phi(phi.value, phi.h)
    _emit(
        event_sink,
        "control",
        f"phi={phi.value:.2f} mode={mode}",
        phi=phi.value,
        qts=phi.qts,
        h=phi.h,
        g=phi.g,
        r=phi.r,
        d=phi.d,
        mode=mode,
        repeated_failures=repeated,
        context_level=task.context_level,
        test_mode=task.test_mode,
    )
    return context, phi, repeated, mode


def _maybe_apply_plan(
    task: ForgeTask,
    context,
    state: ForgeState,
    repeated: float,
    phi,
    *,
    client,
    context_provider: ContextProvider,
    event_sink: object | None,
):
    planner_enabled = getattr(client, "enabled", False) and getattr(
        getattr(client, "config", None), "planner_enabled", True
    )
    if (
        not need_planner(phi.value, phi.h, repeated, state.planner_calls)
        or not planner_enabled
    ):
        return context
    _emit(
        event_sink,
        "planner",
        f"planner engaged for {task.identifier}",
        task_id=task.identifier,
    )
    plan = client.plan(context)
    if plan is None:
        return context
    state.planner_calls += 1
    return context_provider.enrich_with_plan(context, plan)


def _dry_run_execution(
    task: ForgeTask, state: ForgeState, phi, mode: str, repeated: float
) -> TaskExecution:
    metrics = task_metrics(task, state, phi, mode, None, ban_hits=repeated)
    result = TaskResult(
        task.identifier,
        "dry_run",
        "classified and ready for Forge triune evaluation",
        "forge",
        state.lkg_id,
        mode,
        phi.value,
        phi.r,
        metrics=metrics,
    )
    return TaskExecution(result=result)


def _measure_baseline(
    task: ForgeTask,
    repo_root,
    tool_root,
    verifier: VerifierAdapter,
    event_sink: object | None,
) -> float:
    _emit(
        event_sink, "baseline", "measuring baseline coverage", task_id=task.identifier
    )
    return verifier.baseline_coverage(repo_root, tool_root=tool_root)


def _manual_review_execution(
    task: ForgeTask, state: ForgeState, phi, mode: str, repeated: float, detail: str
) -> TaskExecution:
    metrics = task_metrics(task, state, phi, mode, None, ban_hits=repeated)
    result = TaskResult(
        task.identifier,
        "manual_review",
        detail,
        "forge",
        state.lkg_id,
        mode,
        phi.value,
        phi.r,
        metrics=metrics,
    )
    return TaskExecution(result=result)


def _emit_candidates_generated(
    task: ForgeTask, candidates, event_sink: object | None
) -> None:
    _emit(
        event_sink,
        "generated",
        f"generated {len(candidates)} candidate(s)",
        task_id=task.identifier,
        candidates=[candidate.identifier for candidate in candidates],
        files_touched=[list(candidate.files_touched) for candidate in candidates],
        context_level=task.context_level,
        test_mode=task.test_mode,
    )


def _finalize_execution(
    task: ForgeTask,
    state: ForgeState,
    banlist,
    context,
    candidates,
    evaluations: list[EvaluationResult],
    repeated: float,
    mode: str,
    *,
    risk_threshold: float,
    event_sink: object | None,
) -> TaskExecution:
    post_phi = compute_phi(
        evaluations, missing_context=context.missing_context, repeated_failures=repeated
    )
    ranked = sorted(evaluations, key=lambda value: value.score, reverse=True)
    winner = next(
        (
            item
            for item in ranked
            if passes_contract(item, post_phi.value, risk_threshold=risk_threshold)
        ),
        None,
    )
    _remember_evaluations(state, banlist, candidates, evaluations)
    result = _build_result(task, state, post_phi, mode, winner, ranked, repeated)
    accepted_candidate = next(
        (
            candidate
            for candidate in candidates
            if candidate.identifier == result.delta_id
        ),
        None,
    )
    _emit_decision(event_sink, task, result)
    return TaskExecution(
        result=result,
        accepted_candidate=accepted_candidate,
        accepted_evaluation=winner,
        best_evaluation=ranked[0] if ranked else None,
    )


def _remember_evaluations(
    state: ForgeState, banlist, candidates, evaluations: list[EvaluationResult]
) -> None:
    for candidate, evaluation in zip(candidates, evaluations, strict=True):
        register_failure(evaluation, candidate, banlist, state.attempt)
    state.attempt += 1
    state.evaluations.extend(evaluations)
    state.evaluations = state.evaluations[-16:]


def _build_result(
    task: ForgeTask, state: ForgeState, phi, mode: str, winner, ranked, repeated: float
) -> TaskResult:
    status = "promote" if winner is not None else "repair"
    detail = (
        winner.detail
        if winner is not None
        else (
            ranked[0].detail
            if ranked
            else "no candidate satisfied the acceptance contract"
        )
    )
    risk = winner.critique.risk if winner is not None else phi.r
    delta_id = winner.candidate_id if winner is not None else None
    metrics = task_metrics(task, state, phi, mode, winner, ban_hits=repeated)
    return TaskResult(
        task.identifier,
        status,
        detail,
        "forge",
        state.lkg_id,
        mode,
        phi.value,
        risk,
        delta_id=delta_id,
        metrics=metrics,
    )


def _emit_decision(
    event_sink: object | None, task: ForgeTask, result: TaskResult
) -> None:
    _emit(
        event_sink,
        "decision",
        f"{result.status}: {result.detail}",
        task_id=task.identifier,
        status=result.status,
        detail=result.detail,
        phi=result.phi,
        mode=result.mode,
        risk=result.risk,
        delta_id=result.delta_id,
    )


def _evaluate(
    context,
    candidates,
    banlist,
    step,
    repo_root,
    tool_root,
    baseline,
    client,
    *,
    verifier: VerifierAdapter,
    risk_threshold: float,
    event_sink: object | None,
) -> list[EvaluationResult]:
    workers = min(len(candidates), 3)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                evaluate_candidate,
                context,
                candidate,
                banlist,
                step=step,
                tool_root=tool_root,
                baseline_coverage=baseline,
                client=client,
                verifier=verifier,
                risk_threshold=risk_threshold,
                event_sink=event_sink,
            )
            for candidate in candidates
        ]
    return [future.result() for future in futures]


def _emit(
    event_sink: object | None, stage: str, message: str, **fields: object
) -> None:
    if event_sink is None:
        return
    event = {"stage": stage, "message": message}
    event.update(fields)
    event_sink(event)
