"""Adversarial critique for Forge delta candidates."""

from __future__ import annotations

from ..runtime.guards import clamp
from ..types import CandidateDelta, ContextBundle, CritiqueSummary

ATTACKERS = ("logic", "edge", "perf", "security", "concurrency")


def attack_ensemble(
    context: ContextBundle,
    candidate: CandidateDelta,
    client: object | None = None,
) -> CritiqueSummary:
    """Run a bounded heuristic red-team pass, optionally enriched by Ollama."""

    attackers = {name: _attack_score(name, candidate.patch) for name in ATTACKERS}
    findings = tuple(_findings(candidate.patch))
    counterfactuals = tuple(_counterfactuals(context, candidate))
    risk = clamp(max(attackers.values(), default=0.0))
    if client is not None and getattr(client, "enabled", False):
        model_findings = _model_findings(client, context, candidate)
        risk = clamp(max(risk, _coerce_risk(model_findings.get("risk", 0.0))))
        findings = _merge_unique(
            findings, tuple(str(item) for item in model_findings.get("findings", []))
        )
        counterfactuals = _merge_unique(
            counterfactuals,
            tuple(str(item) for item in model_findings.get("counterfactuals", [])),
        )
        for name, value in dict(model_findings.get("attackers", {})).items():
            attackers[str(name)] = clamp(
                max(_coerce_risk(value), attackers.get(str(name), 0.0))
            )
    return CritiqueSummary(
        risk=risk,
        findings=findings,
        attackers=attackers,
        counterfactuals=counterfactuals,
    )


def _attack_score(name: str, patch: str) -> float:
    lower = patch.lower()
    if name == "logic":
        return clamp(
            (0.25 if "-assert " in patch or "-raise " in patch else 0.0)
            + (0.15 if "\n+    pass" in patch else 0.0)
        )
    if name == "edge":
        return clamp(
            0.2 if any(token in lower for token in ("[0]", "index(", "split(")) else 0.0
        )
    if name == "perf":
        return clamp(
            0.3
            if "while true" in lower or "for " in lower and " for " in lower
            else 0.0
        )
    if name == "security":
        return clamp(
            0.9
            if any(
                token in lower
                for token in ("shell=true", "os.system(", "eval(", "exec(")
            )
            else 0.0
        )
    if name == "concurrency":
        return clamp(
            0.45
            if any(
                token in lower
                for token in ("threadpoolexecutor", "create_task(", "threading.")
            )
            else 0.0
        )
    return 0.0


def _findings(patch: str) -> list[str]:
    lower = patch.lower()
    findings: list[str] = []
    if "shell=true" in lower or "os.system(" in lower:
        findings.append("security: shell-based execution path introduced")
    if "eval(" in lower or "exec(" in lower:
        findings.append("security: dynamic code execution introduced")
    if "-assert " in patch or "-raise " in patch:
        findings.append("logic: safety checks were removed")
    if "while true" in lower:
        findings.append("perf: unbounded loop introduced")
    if "threadpoolexecutor" in lower or "create_task(" in lower:
        findings.append("concurrency: new scheduling path requires race coverage")
    return findings


def _counterfactuals(context: ContextBundle, candidate: CandidateDelta) -> list[str]:
    prompts = ["smallest break", "largest break", "invalid inputs", "boundary cases"]
    if any("test" in path for path in candidate.files_touched):
        prompts.append("ordering/race")
    if context.ban_hotspots:
        prompts.append(f"hot region retry: {context.ban_hotspots[0]}")
    return prompts


def _model_findings(
    client: object, context: ContextBundle, candidate: CandidateDelta
) -> dict[str, object]:
    aggregate: dict[str, object] = {
        "risk": 0.0,
        "findings": [],
        "counterfactuals": [],
        "attackers": {},
    }
    for mode in ATTACKERS:
        response = getattr(client, "critique")(context, candidate.patch, mode)
        if response:
            aggregate["risk"] = max(
                _coerce_risk(aggregate["risk"]), _coerce_risk(response.get("risk", 0.0))
            )
            aggregate["findings"] = list(
                _merge_unique(
                    tuple(str(item) for item in list(aggregate["findings"])),
                    tuple(str(item) for item in response.get("findings", [])),
                )
            )
            aggregate["counterfactuals"] = list(
                _merge_unique(
                    tuple(str(item) for item in list(aggregate["counterfactuals"])),
                    tuple(str(item) for item in response.get("counterfactuals", [])),
                )
            )
            aggregate["attackers"][mode] = _coerce_risk(response.get("risk", 0.0))
    return aggregate


def _merge_unique(existing: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(existing)
    seen = set(existing)
    for item in extra:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return tuple(merged)


def _coerce_risk(value: object) -> float:
    """Normalize model risk values into a 0..1 float."""

    if isinstance(value, (int, float)):
        return clamp(float(value))
    text = str(value).strip().lower()
    mapping = {
        "none": 0.0,
        "low": 0.25,
        "medium": 0.5,
        "med": 0.5,
        "high": 0.75,
        "critical": 1.0,
    }
    if text in mapping:
        return mapping[text]
    try:
        return clamp(float(text))
    except ValueError:
        return 0.5
