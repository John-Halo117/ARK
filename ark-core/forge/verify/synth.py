"""Synthesized executable checks derived from critique findings."""

from __future__ import annotations

from ..types import CandidateDelta, CritiqueSummary


def run_synth_checks(
    candidate: CandidateDelta, critique: CritiqueSummary
) -> tuple[bool, list[dict[str, object]]]:
    """Turn critique findings into bounded executable checks."""

    checks = _checks_for(candidate, critique)
    results = [
        {"name": name, "passed": passed, "detail": detail}
        for name, passed, detail in checks
    ]
    return all(item["passed"] for item in results), results


def _checks_for(
    candidate: CandidateDelta, critique: CritiqueSummary
) -> list[tuple[str, bool, str]]:
    patch = candidate.patch.lower()
    checks: list[tuple[str, bool, str]] = []
    if any("shell" in finding.lower() for finding in critique.findings):
        checks.append(
            (
                "no_shell_escape",
                "shell=true" not in patch and "os.system(" not in patch,
                "reject shell execution paths",
            )
        )
    if any(
        "dynamic code execution" in finding.lower() for finding in critique.findings
    ):
        checks.append(
            (
                "no_dynamic_exec",
                "eval(" not in patch and "exec(" not in patch,
                "reject eval/exec in accepted deltas",
            )
        )
    if any("unbounded loop" in finding.lower() for finding in critique.findings):
        checks.append(
            (
                "no_unbounded_loops",
                "while true" not in patch,
                "accepted deltas cannot introduce while True",
            )
        )
    return checks
