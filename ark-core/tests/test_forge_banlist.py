"""Forge failure-memory checks."""

from __future__ import annotations

from forge.memory.ban import BanList, failure_record
from forge.transform.apply import extract_changed_files
from forge.types import CandidateDelta, CritiqueSummary, EvaluationResult, VerifySummary
from forge.verify.eval import register_failure


def test_banlist_blocks_repeats_then_decays() -> None:
    patch = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    record = failure_record(patch, "executor", "candidate_failure")
    banlist = BanList()
    banlist.add(record, step=0)

    assert banlist.is_blocked(record, step=0)
    assert banlist.is_blocked(record, step=2)
    assert not banlist.is_blocked(record, step=20)


def test_register_failure_uses_caller_risk_threshold() -> None:
    patch = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    candidate = CandidateDelta(
        identifier="delta-1",
        patch=patch,
        strategy="executor",
        seed=1,
        files_touched=extract_changed_files(patch),
    )
    result = EvaluationResult(
        candidate_id=candidate.identifier,
        blocked=False,
        critique=CritiqueSummary(risk=0.4, findings=(), attackers={}),
        verify=VerifySummary(
            tests_ok=True,
            synth_ok=True,
            lint_ok=True,
            types_ok=True,
            coverage_delta=0.0,
            no_new_failures=True,
        ),
        detail="passed",
        diff_cost=0.0,
        score=1.0,
    )
    banlist = BanList()

    register_failure(result, candidate, banlist, step=0, risk_threshold=0.5)

    assert banlist.export() == []
