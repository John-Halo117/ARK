"""Triune evaluation: generate, critique, verify."""

from __future__ import annotations

from ..exec.sandbox import sandbox
from ..memory.ban import BanList, failure_record
from ..runtime.config import DEFAULT_POLICY_CONFIG
from ..transform.apply import apply_unified_diff
from ..types import (
    CandidateDelta,
    ContextBundle,
    CritiqueSummary,
    EvaluationResult,
    VerifySummary,
)
from .adapters import PythonVerifierAdapter, VerifierAdapter
from .redteam import attack_ensemble
from .synth import run_synth_checks

TAU = DEFAULT_POLICY_CONFIG.risk_threshold


def evaluate_candidate(
    context: ContextBundle,
    candidate: CandidateDelta,
    banlist: BanList,
    *,
    step: int,
    tool_root,
    baseline_coverage: float | None = None,
    client: object | None = None,
    verifier: VerifierAdapter | None = None,
    risk_threshold: float = TAU,
    event_sink: object | None = None,
) -> EvaluationResult:
    """Evaluate one delta in isolation."""

    verifier_impl = verifier or PythonVerifierAdapter()
    blocked = _blocked_repeat_candidate(candidate, banlist, step, event_sink)
    if blocked is not None:
        return blocked
    with sandbox(context.repo_root) as sandbox_root:
        invalid = _apply_candidate_patch(candidate, sandbox_root, event_sink)
        if invalid is not None:
            return invalid
        verification = _run_verification(
            context,
            candidate,
            sandbox_root,
            tool_root=tool_root,
            baseline_coverage=baseline_coverage,
            verifier=verifier_impl,
            event_sink=event_sink,
        )
        critique, synth_ok, synth_results = _run_attacks(
            context, candidate, client=client, event_sink=event_sink
        )
    verify = _build_verify_summary(verification, synth_ok, synth_results)
    result = _build_evaluation_result(
        candidate, verify, critique, risk_threshold=risk_threshold
    )
    _emit_candidate_done(candidate, result, event_sink)
    return result


def _blocked_repeat_candidate(
    candidate: CandidateDelta, banlist: BanList, step: int, event_sink: object | None
) -> EvaluationResult | None:
    _emit(
        event_sink,
        "candidate_start",
        f"evaluating {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    signature = failure_record(candidate.patch, candidate.strategy, "candidate_failure")
    if not banlist.is_blocked(signature, step):
        return None
    _emit(
        event_sink,
        "candidate_blocked",
        f"blocked repeat failure for {candidate.identifier}",
        candidate_id=candidate.identifier,
        risk=1.0,
        detail="blocked by decayed no-repeat memory",
    )
    return _blocked(candidate.identifier)


def _apply_candidate_patch(
    candidate: CandidateDelta, sandbox_root, event_sink: object | None
) -> EvaluationResult | None:
    try:
        _emit(
            event_sink,
            "candidate_apply",
            f"applying {candidate.identifier} in sandbox",
            candidate_id=candidate.identifier,
        )
        apply_unified_diff(sandbox_root, candidate.patch)
    except ValueError:
        _emit(
            event_sink,
            "candidate_invalid",
            f"invalid patch for {candidate.identifier}",
            candidate_id=candidate.identifier,
            risk=1.0,
            detail="candidate patch was invalid",
        )
        return _invalid_patch(candidate.identifier, "candidate patch was invalid")
    return None


def _run_verification(
    context: ContextBundle,
    candidate: CandidateDelta,
    sandbox_root,
    *,
    tool_root,
    baseline_coverage: float | None,
    verifier: VerifierAdapter,
    event_sink: object | None,
):
    baseline = (
        baseline_coverage
        if baseline_coverage is not None
        else verifier.baseline_coverage(context.repo_root, tool_root=tool_root)
    )
    _emit(
        event_sink,
        "candidate_tests",
        f"running tests for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    verification = verifier.run(
        context, sandbox_root, tool_root=tool_root, baseline_coverage=baseline
    )
    _emit(
        event_sink,
        "candidate_lint",
        f"running lint for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    _emit(
        event_sink,
        "candidate_types",
        f"running typecheck for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    _emit(
        event_sink,
        "candidate_gate",
        f"running redteam gate for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    return verification


def _run_attacks(
    context: ContextBundle,
    candidate: CandidateDelta,
    *,
    client: object | None,
    event_sink: object | None,
):
    _emit(
        event_sink,
        "candidate_attack",
        f"running critique for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    critique = attack_ensemble(context, candidate, client=client)
    _emit(
        event_sink,
        "candidate_synth",
        f"running synthesized checks for {candidate.identifier}",
        candidate_id=candidate.identifier,
    )
    synth_ok, synth_results = run_synth_checks(candidate, critique)
    return critique, synth_ok, synth_results


def _build_verify_summary(verification, synth_ok: bool, synth_results) -> VerifySummary:
    tests = verification.tests
    lint = verification.lint
    types = verification.types
    gate = verification.gate
    tests_ok = bool(tests["ok"]) and bool(gate["ok"])
    return VerifySummary(
        tests_ok=tests_ok,
        synth_ok=synth_ok,
        lint_ok=bool(lint["ok"]),
        types_ok=bool(types["ok"]),
        coverage_delta=float(tests["coverage"]) - float(verification.baseline_coverage),
        no_new_failures=tests_ok,
        details={
            "tests": tests,
            "lint": lint,
            "types": types,
            "gate": gate,
            "synth": synth_results,
        },
    )


def _build_evaluation_result(
    candidate: CandidateDelta,
    verify: VerifySummary,
    critique: CritiqueSummary,
    *,
    risk_threshold: float,
) -> EvaluationResult:
    detail = (
        "all gates passed"
        if verify.passed() and critique.risk <= risk_threshold
        else "candidate requires repair"
    )
    return EvaluationResult(
        candidate_id=candidate.identifier,
        blocked=False,
        critique=critique,
        verify=verify,
        detail=detail,
        diff_cost=_diff_cost(candidate.patch),
        score=_score(verify.passed(), critique.risk, candidate.patch),
    )


def _emit_candidate_done(
    candidate: CandidateDelta, result: EvaluationResult, event_sink: object | None
) -> None:
    verify = result.verify
    critique = result.critique
    _emit(
        event_sink,
        "candidate_done",
        f"{candidate.identifier}: tests={'ok' if verify.tests_ok else 'fail'} risk={critique.risk:.2f}",
        candidate_id=candidate.identifier,
        risk=critique.risk,
        score=result.score,
        detail=result.detail,
        tests_ok=verify.tests_ok,
        lint_ok=verify.lint_ok,
        types_ok=verify.types_ok,
        synth_ok=verify.synth_ok,
        coverage_delta=verify.coverage_delta,
        findings=list(critique.findings),
        attackers=critique.attackers,
        counterfactuals=list(critique.counterfactuals),
    )


def register_failure(
    result: EvaluationResult,
    candidate: CandidateDelta,
    banlist: BanList,
    step: int,
    *,
    risk_threshold: float = TAU,
) -> None:
    """Remember failed candidates with decay-aware signatures."""

    if (
        result.blocked
        or result.verify.passed()
        and result.critique.risk <= risk_threshold
    ):
        return
    banlist.add(
        failure_record(candidate.patch, candidate.strategy, "candidate_failure"), step
    )


def passes_contract(
    result: EvaluationResult, phi: float, *, risk_threshold: float = TAU
) -> bool:
    """Apply the strict acceptance contract."""

    return (
        not result.blocked
        and result.verify.passed()
        and result.critique.risk <= risk_threshold
        and phi >= DEFAULT_POLICY_CONFIG.accept_phi_threshold
    )


def _blocked(candidate_id: str) -> EvaluationResult:
    verify = VerifySummary(
        False, False, False, False, -1.0, False, details={"reason": "banlist"}
    )
    critique = CritiqueSummary(
        risk=1.0, findings=("blocked by decayed no-repeat memory",), attackers={}
    )
    return EvaluationResult(
        candidate_id=candidate_id,
        blocked=True,
        critique=critique,
        verify=verify,
        detail="blocked by no-repeat memory",
        diff_cost=1.0,
        score=0.0,
    )


def _invalid_patch(candidate_id: str, reason: str) -> EvaluationResult:
    verify = VerifySummary(
        False, False, False, False, -1.0, False, details={"reason": reason}
    )
    critique = CritiqueSummary(
        risk=1.0,
        findings=("candidate patch could not be applied cleanly",),
        attackers={"logic": 1.0},
    )
    return EvaluationResult(
        candidate_id=candidate_id,
        blocked=False,
        critique=critique,
        verify=verify,
        detail=f"candidate patch was invalid: {reason}",
        diff_cost=1.0,
        score=0.0,
    )


def _diff_cost(patch: str) -> float:
    changed = [
        line
        for line in patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    return min(1.0, len(changed) / 80.0)


def _score(verified: bool, risk: float, patch: str) -> float:
    cost = _diff_cost(patch)
    return max(
        0.0, (0.5 if verified else 0.0) + (0.3 * (1.0 - risk)) + (0.2 * (1.0 - cost))
    )


def _emit(
    event_sink: object | None, stage: str, message: str, **fields: object
) -> None:
    if event_sink is None:
        return
    event = {"stage": stage, "message": message}
    event.update(fields)
    event_sink(event)
