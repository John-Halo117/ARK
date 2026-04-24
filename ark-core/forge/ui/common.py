"""Shared Forge UI datatypes, rendering, and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable

from ..models.discovery import (
    compact_runtime_summary,
    detect_ollama_endpoint,
    choose_model,
)
from ..models.ollama_client import OllamaClient, OllamaConfig
from ..runtime.config import DEFAULT_UI_STATE_CONFIG
from ..transform.apply import extract_changed_files

PATCH_APPLY_ERROR = "patch could not be applied cleanly"
PATCH_REVERT_ERROR = "revert patch could not be applied cleanly"


@dataclass(frozen=True)
class HistoryRecord:
    """One persisted Forge run shown in operator UIs."""

    label: str
    identifier: str
    status: str
    detail: str
    phi: float
    mode: str
    risk: float
    result_path: Path
    patch_path: Path | None
    diff_text: str
    files_touched: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunRequest:
    """One UI-submitted Forge request."""

    task_text: str
    files: tuple[str, ...]
    repo_root: Path
    apply_accepted: bool
    planner_enabled: bool
    redteam_enabled: bool
    debug_enabled: bool
    auto_loop: bool
    mode_override: str | None
    risk_threshold: float
    context_level: int
    test_mode: str
    timeout_s: int
    num_ctx: int
    preferred_model: str | None
    preferred_url: str | None


@dataclass
class CandidateRecord:
    """Live candidate state shown while Forge is evaluating deltas."""

    identifier: str
    status: str = "proposed"
    patch: str = ""
    files_touched: tuple[str, ...] = ()
    strategy: str = ""
    seed: int = 0
    risk: float = 0.0
    score: float = 0.0
    line_count: int = 0
    hunk_count: int = 0
    tests_ok: bool | None = None
    lint_ok: bool | None = None
    types_ok: bool | None = None
    synth_ok: bool | None = None
    coverage_delta: float = 0.0
    findings: tuple[str, ...] = ()
    attackers: dict[str, float] = field(default_factory=dict)
    counterfactuals: tuple[str, ...] = ()
    detail: str = ""

    @property
    def label(self) -> str:
        file_count = len(self.files_touched)
        return " • ".join(
            [
                _candidate_status_label(self.status),
                _risk_label(self.risk),
                _count_label(file_count, "file"),
            ]
        )


def artifacts_dir_for_repo(repo_root: Path) -> Path:
    return repo_root / ".forge" / "artifacts"


def load_history_records(
    artifacts_dir: Path, *, limit: int | None = None
) -> list[HistoryRecord]:
    if not artifacts_dir.exists():
        return []
    cap = limit or DEFAULT_UI_STATE_CONFIG.max_history_records
    result_paths = sorted(artifacts_dir.glob("*.result.json"), reverse=True)[:cap]
    return [
        _history_record_from_payload(_load_json(path), result_path=path)
        for path in result_paths
    ]


def history_record_from_result(result: dict[str, Any]) -> HistoryRecord:
    result_path = Path(str(result.get("artifacts", {}).get("result", ".")))
    return _history_record_from_payload(result, result_path=result_path)


def render_control_panel(
    runtime_summary: str,
    machine: dict[str, Any],
    record: HistoryRecord | CandidateRecord | None,
    *,
    debug: bool,
) -> str:
    status = str(machine.get("status", "WAITING"))
    mode = _mode_label(str(machine.get("mode", "AUTO")))
    test_mode = _test_mode_label(
        str(machine.get("test_mode", DEFAULT_UI_STATE_CONFIG.test_mode))
    )
    context_level = int(
        machine.get("context_level", DEFAULT_UI_STATE_CONFIG.context_level)
    )
    tool_profile = str(
        machine.get("tool_profile", DEFAULT_UI_STATE_CONFIG.tool_profile)
    )
    lines = [
        f"[{status}]",
        f"AI status: {runtime_summary}",
        f"Right now: {_stage_summary(str(machine.get('stage_label', 'idle')))}",
        f"Tool style: {_tool_profile_label(tool_profile)}",
        f"Search style: {mode}",
        f"Check depth: {test_mode}",
        f"Context scope: {_context_label(context_level)}",
        f"Safety bar: {_risk_threshold_label(float(machine.get('risk_threshold', DEFAULT_UI_STATE_CONFIG.risk_threshold)))}",
    ]
    if record is not None:
        lines.extend([""])
        if isinstance(record, HistoryRecord):
            lines.extend(
                [
                    f"Selected result: {_history_status_label(record.status)}",
                    f"Confidence: {_risk_label(record.risk)}",
                    f"What happened: {record.detail or 'Saved result ready to inspect.'}",
                ]
            )
        else:
            lines.extend(
                [
                    f"Selected option: {_candidate_status_label(record.status)}",
                    f"Confidence: {_risk_label(record.risk)}",
                    f"Size: {_count_label(record.hunk_count, 'change')} across {_count_label(len(record.files_touched), 'file')}",
                    f"What Forge sees: {record.detail or 'Forge is still checking this option.'}",
                ]
            )
    if debug:
        lines.extend(
            [
                "",
                "Debug",
                (
                    f"Φ={machine.get('phi', 0.0):.2f} | "
                    f"Q/H/G/R/D={machine.get('qts', 0.0):.2f}/"
                    f"{machine.get('h', 0.0):.2f}/"
                    f"{machine.get('g', 0.0):.2f}/"
                    f"{machine.get('r', 0.0):.2f}/"
                    f"{machine.get('d', 0.0):.2f}"
                ),
                (
                    f"Branches: {machine.get('branch_count', 0)} | "
                    f"Ban hits: {machine.get('ban_hits', 0)} | "
                    f"Last event: {machine.get('last_event', 'ready')}"
                ),
                json.dumps(machine, indent=2, sort_keys=True),
            ]
        )
    return "\n".join(lines)


def render_status_strip(
    runtime_summary: str,
    machine: dict[str, Any],
    *,
    live_count: int,
    history_count: int,
    selected_label: str,
) -> str:
    task = str(machine.get("task", "")).strip() or "No task loaded"
    status = str(machine.get("status", "WAITING"))
    stage = _stage_summary(str(machine.get("stage_label", "idle")))
    mode = _mode_label(str(machine.get("mode", "AUTO")))
    option_text = _count_label(live_count, "live option")
    history_text = _count_label(history_count, "saved run")
    return (
        f"[{status}] {task}\n"
        f"Now: {stage} | Search: {mode} | {option_text} | {history_text}\n"
        f"AI: {runtime_summary} | Focus: {selected_label}"
    )


def command_legend() -> list[tuple[str, str]]:
    return list(DEFAULT_UI_STATE_CONFIG.command_legend)


def example_tasks() -> list[str]:
    return list(DEFAULT_UI_STATE_CONFIG.example_tasks)


def workflow_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": preset.identifier,
            "label": preset.label,
            "description": preset.description,
            "mode": preset.mode_override,
            "context": preset.context_level,
            "tests": preset.test_mode,
            "auto": preset.auto_loop,
            "planner": preset.planner_enabled,
        }
        for preset in DEFAULT_UI_STATE_CONFIG.workflow_presets
    ]


def tool_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": profile.identifier,
            "label": profile.label,
            "description": profile.description,
            "mode": profile.mode_override,
            "context": profile.context_level,
            "tests": profile.test_mode,
            "auto": profile.auto_loop,
            "planner": profile.planner_enabled,
            "redteam": profile.redteam_enabled,
        }
        for profile in DEFAULT_UI_STATE_CONFIG.tool_profiles
    ]


def render_command_legend() -> str:
    return "\n".join(
        f"{command:<14} {meaning}" for command, meaning in command_legend()
    )


def render_files_panel(record: HistoryRecord | CandidateRecord | None) -> str:
    if record is None or not record.files_touched:
        return "Files Forge plans to touch\n\nNothing selected yet."
    return "Files Forge plans to touch\n\n" + "\n".join(
        f"- {path}" for path in record.files_touched
    )


def render_redteam_panel(
    record: HistoryRecord | CandidateRecord | None, *, expanded: bool
) -> str:
    if record is None:
        return "Risk review\n\nNo result selected yet."
    if isinstance(record, HistoryRecord):
        critique = dict(record.payload.get("metrics", {}).get("critique", {}))
        attackers = dict(critique.get("attackers", {}))
        findings = list(critique.get("findings", []))
        counterfactuals = list(critique.get("counterfactuals", []))
        risk = record.risk
    else:
        attackers = dict(record.attackers)
        findings = list(record.findings)
        counterfactuals = list(record.counterfactuals)
        risk = record.risk
    lines = [f"Risk: {risk:.2f}"]
    if attackers:
        lines.extend(
            f"{name}: {float(value):.2f}" for name, value in sorted(attackers.items())
        )
    if expanded and findings:
        lines.extend(["", "Findings"] + [f"- {item}" for item in findings])
    if expanded and counterfactuals:
        lines.extend(
            ["", "Counterfactuals"] + [f"- {item}" for item in counterfactuals]
        )
    return "Risk review\n\n" + "\n".join(lines)


def render_test_panel(
    record: HistoryRecord | CandidateRecord | None, *, expanded: bool
) -> str:
    if record is None:
        return "Checks\n\nNo result selected yet."
    if isinstance(record, HistoryRecord):
        verify = dict(record.payload.get("metrics", {}).get("verify", {}))
        lines = [
            f"Result: {record.status}",
            f"Repo tests: {_status_icon(bool(verify.get('tests_ok', record.payload.get('metrics', {}).get('tests', False))))}",
            f"Added safeguards: {_status_icon(bool(verify.get('synth_ok', False)))}",
            f"Style checks: {_status_icon(bool(verify.get('lint_ok', False)))}",
            f"Type checks: {_status_icon(bool(verify.get('types_ok', False)))}",
            f"Coverage change: {float(verify.get('coverage_delta', record.payload.get('metrics', {}).get('coverage_delta', 0.0))):+.2f}",
        ]
        if expanded:
            details = dict(verify.get("details", {}))
            if details:
                lines.extend(["", json.dumps(details, indent=2, sort_keys=True)])
    else:
        lines = [
            f"Result: {record.status}",
            f"Repo tests: {_status_icon(record.tests_ok)}",
            f"Added safeguards: {_status_icon(record.synth_ok)}",
            f"Style checks: {_status_icon(record.lint_ok)}",
            f"Type checks: {_status_icon(record.types_ok)}",
            f"Coverage change: {record.coverage_delta:+.2f}",
        ]
        if expanded and record.detail:
            lines.extend(["", record.detail])
    return "Checks\n\n" + "\n".join(lines)


def render_candidate_summary(
    candidates: dict[str, CandidateRecord], selected_candidate_id: str | None
) -> str:
    if not candidates:
        return "Candidates\n\nNo live candidates yet."
    lines = []
    for candidate in candidates.values():
        prefix = ">" if candidate.identifier == selected_candidate_id else " "
        lines.append(f"{prefix} {candidate.label}")
    return "Candidates\n\n" + "\n".join(lines)


def quickstart_steps() -> list[str]:
    return list(DEFAULT_UI_STATE_CONFIG.quickstart)


def runtime_doctor_steps(runtime_summary: str) -> list[str]:
    if "not detected" in runtime_summary.lower():
        return [
            "Open the Ollama app and wait a few seconds.",
            "Click Check Tools.",
            "If it still fails, restart Ollama and try again.",
        ]
    if "(models: none)" in runtime_summary.lower():
        return [
            "Ollama is running, but no coding model is loaded yet.",
            "Run `ollama pull qwen3-coder:30b` once.",
            "Click Check Tools again after the model finishes loading.",
        ]
    return list(DEFAULT_UI_STATE_CONFIG.runtime_help_ready)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _history_record_from_payload(
    payload: dict[str, Any], *, result_path: Path
) -> HistoryRecord:
    artifacts = dict(payload.get("artifacts", {}))
    patch_path_raw = artifacts.get("accepted_patch")
    patch_path = Path(str(patch_path_raw)) if patch_path_raw else None
    diff_text = (
        patch_path.read_text(encoding="utf-8")
        if patch_path is not None and patch_path.exists()
        else json.dumps(payload, indent=2, sort_keys=True)
    )
    metrics = dict(payload.get("metrics", {}))
    files_touched = (
        tuple(metrics.get("files_touched", [])) or extract_changed_files(diff_text)
        if patch_path is not None
        else tuple(metrics.get("files_touched", []))
    )
    file_count = len(files_touched)
    status = _history_status_label(str(payload.get("status", "unknown")))
    risk = _risk_label(float(payload.get("risk", 0.0)))
    label = f"{status} • {risk} • {_count_label(file_count, 'file')} • {payload.get('identifier', 'task')}"
    return HistoryRecord(
        label=label,
        identifier=str(payload.get("identifier", result_path.stem)),
        status=str(payload.get("status", "unknown")),
        detail=str(payload.get("detail", "")),
        phi=float(payload.get("phi", 0.0)),
        mode=str(payload.get("mode", "AUTO")),
        risk=float(payload.get("risk", 0.0)),
        result_path=result_path,
        patch_path=patch_path,
        diff_text=diff_text,
        files_touched=files_touched,
        payload=payload,
    )


def split_files(raw: str) -> list[str]:
    return [item for item in raw.replace(",", " ").split() if item]


def parse_command(command: str) -> tuple[str, str, list[str]] | None:
    raw = command.lstrip(":").strip()
    if not raw:
        return None
    parts = raw.split()
    if not parts:
        return None
    return raw, parts[0].lower(), [part.lower() for part in parts[1:]]


def _status_icon(value: bool | None) -> str:
    if value is None:
        return "waiting"
    return "passed" if value else "failed"


def _candidate_status_label(status: str) -> str:
    mapping = {
        "proposed": "New option",
        "queued": "Queued",
        "applying": "Applying",
        "invalid": "Invalid",
        "testing": "Checking",
        "linting": "Style check",
        "types": "Type check",
        "gate": "Safety review",
        "attacking": "Stress testing",
        "synth": "Adding safeguards",
        "done": "Ready to review",
        "blocked": "Blocked",
    }
    return mapping.get(status, status.replace("_", " ").title())


def _count_label(value: int, noun: str) -> str:
    suffix = "" if value == 1 else "s"
    return f"{value} {noun}{suffix}"


def _mode_label(mode: str) -> str:
    mapping = {
        "AUTO": "Balanced",
        "SIMPLE": "Focused",
        "BISECT": "Two options",
        "TRISECT": "Wide search",
    }
    return mapping.get(mode.upper(), mode.title())


def _test_mode_label(test_mode: str) -> str:
    mapping = {
        "default": "Balanced",
        "fast": "Faster checks",
        "full": "Deep checks",
    }
    return mapping.get(test_mode.lower(), test_mode.title())


def _tool_profile_label(profile: str) -> str:
    for item in DEFAULT_UI_STATE_CONFIG.tool_profiles:
        if item.identifier == profile:
            return item.label
    return profile.title()


def _risk_label(risk: float) -> str:
    if risk <= 0.15:
        return "Low risk"
    if risk <= 0.35:
        return "Moderate risk"
    if risk <= 0.60:
        return "Elevated risk"
    return "High risk"


def _risk_threshold_label(value: float) -> str:
    return f"{value:.2f} max risk before Forge blocks a change"


def _context_label(level: int) -> str:
    mapping = {
        0: "Tight focus",
        1: "Normal scope",
        2: "Broader repo scan",
        3: "Deep repo scan",
    }
    return mapping.get(level, f"Level {level}")


def _stage_summary(stage: str) -> str:
    cleaned = stage.replace("_", " ").strip().lower()
    mapping = {
        "idle": "Waiting for your task",
        "iter 1": "Starting the first pass",
        "queued": "Task is queued",
        "runtime unavailable": "Waiting for the AI runtime",
        "complete": "Ready for you to review",
        "blocked": "Stopped because something needs attention",
        "interrupted": "Paused safely",
        "decision": "Deciding whether a change is safe",
        "testing": "Running checks",
        "attacking": "Stress-testing the change",
        "planning": "Figuring out the safest approach",
        "building context": "Reading the relevant code",
        "evaluating": "Comparing options",
    }
    return mapping.get(cleaned, cleaned.capitalize())


def _history_status_label(status: str) -> str:
    mapping = {
        "promote": "Ready to use",
        "manual_review": "Needs your review",
        "repair": "Needs another pass",
    }
    return mapping.get(status, status.replace("_", " ").title())


def _pipeline_line(stage: str) -> str:
    steps = [
        "CLASSIFY",
        "CONTEXT",
        "PLAN",
        "GENERATE",
        "VERIFY",
        "ATTACK",
        "DECIDE",
        "COMMIT",
    ]
    bucket = _pipeline_bucket(stage)
    if bucket == "BLOCKED":
        return " -> ".join([*steps, "[BLOCKED]"])
    highlighted: list[str] = []
    current_index = steps.index(bucket) if bucket in steps else -1
    for index, step in enumerate(steps):
        if index < current_index:
            highlighted.append(f"✓{step}")
        elif index == current_index:
            highlighted.append(f"[{step}]")
        else:
            highlighted.append(step)
    return " -> ".join(highlighted)


def _pipeline_bucket(stage: str) -> str:
    mapping = {
        "idle": "CLASSIFY",
        "queued": "CLASSIFY",
        "classify_start": "CLASSIFY",
        "runtime_check": "CLASSIFY",
        "context": "CONTEXT",
        "control": "PLAN",
        "planner": "PLAN",
        "baseline": "GENERATE",
        "generate": "GENERATE",
        "generated": "GENERATE",
        "candidate_proposed": "GENERATE",
        "candidate_start": "VERIFY",
        "candidate_apply": "VERIFY",
        "candidate_invalid": "VERIFY",
        "candidate_tests": "VERIFY",
        "candidate_lint": "VERIFY",
        "candidate_types": "VERIFY",
        "candidate_gate": "ATTACK",
        "candidate_attack": "ATTACK",
        "candidate_synth": "ATTACK",
        "candidate_done": "DECIDE",
        "decision": "DECIDE",
        "apply": "COMMIT",
        "complete": "COMMIT",
        "blocked": "BLOCKED",
    }
    return mapping.get(stage, "CLASSIFY")


def stage_label(stage: str) -> str:
    mapping = {
        "queued": "queued",
        "classify_start": "classifying",
        "runtime_check": "checking runtime",
        "context": "building context",
        "control": "updating Φ",
        "planner": "planning",
        "baseline": "baseline",
        "generate": "generating",
        "generated": "generated",
        "candidate_proposed": "candidate proposed",
        "candidate_start": "evaluating",
        "candidate_apply": "applying sandbox patch",
        "candidate_invalid": "invalid patch",
        "candidate_tests": "testing",
        "candidate_lint": "linting",
        "candidate_types": "typechecking",
        "candidate_gate": "gate checks",
        "candidate_attack": "attacking",
        "candidate_synth": "synth tests",
        "candidate_done": "candidate done",
        "decision": "decision",
        "apply": "applying",
        "complete": "complete",
        "blocked": "blocked",
    }
    return mapping.get(stage, stage.replace("_", " "))


def status_from_result(result: dict[str, Any]) -> str:
    if result.get("status") == "promote":
        return "COMMIT READY"
    if result.get("status") == "manual_review":
        return "BLOCKED"
    if result.get("status") == "repair":
        return "WAITING"
    return "WAITING"


def event_status(stage: str, event: dict[str, Any], *, current: str) -> str:
    if stage == "planner":
        return "PLANNING"
    if stage in {
        "candidate_tests",
        "candidate_lint",
        "candidate_types",
        "candidate_synth",
    }:
        return "TESTING"
    if stage in {"candidate_gate", "candidate_attack"}:
        return "ATTACKING"
    if stage == "decision":
        return "COMMIT READY" if event.get("status") == "promote" else "WAITING"
    if stage == "blocked":
        return "BLOCKED"
    if stage in {"apply", "complete"}:
        return current if current != "RUNNING" else "WAITING"
    if stage in {
        "context",
        "control",
        "baseline",
        "generate",
        "generated",
        "candidate_proposed",
        "candidate_start",
        "candidate_apply",
    }:
        return "RUNNING"
    return current


def candidate_status(stage: str, current: str) -> str:
    mapping = {
        "candidate_proposed": "proposed",
        "candidate_start": "queued",
        "candidate_apply": "applying",
        "candidate_invalid": "invalid",
        "candidate_tests": "testing",
        "candidate_lint": "linting",
        "candidate_types": "types",
        "candidate_gate": "gate",
        "candidate_attack": "attacking",
        "candidate_synth": "synth",
        "candidate_done": "done",
        "candidate_blocked": "blocked",
    }
    return mapping.get(stage, current)


def record_diff_text(record: HistoryRecord | CandidateRecord | None) -> str:
    if record is None:
        return "No diffs yet."
    if isinstance(record, HistoryRecord):
        return record.diff_text
    return record.patch or "Candidate has no patch payload."


def selected_label(record: HistoryRecord | CandidateRecord | None) -> str:
    if record is None:
        return "Nothing selected"
    if isinstance(record, HistoryRecord):
        return f"Run {record.identifier}"
    return f"Δ {record.identifier} ({record.status})"


def find_candidate_index(
    candidates: dict[str, CandidateRecord], candidate_id: str | None
) -> int | None:
    if candidate_id is None:
        return None
    try:
        return list(candidates).index(candidate_id)
    except ValueError:
        return None


def find_history_index(
    records: list[HistoryRecord], identifier: str | None
) -> int | None:
    if identifier is None:
        return None
    for index, record in enumerate(records):
        if record.identifier == identifier:
            return index
    return None


def task_identifier(task_text: str) -> str:
    words = [token for token in task_text.lower().replace("/", " ").split() if token]
    base = "-".join(words[:6]) or "forge-ui-task"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in base)
    return safe.strip("-") or "forge-ui-task"


def candidate_payload(candidate: CandidateRecord) -> dict[str, Any]:
    return {
        "identifier": candidate.identifier,
        "status": candidate.status,
        "patch": candidate.patch,
        "files_touched": list(candidate.files_touched),
        "strategy": candidate.strategy,
        "seed": candidate.seed,
        "risk": candidate.risk,
        "score": candidate.score,
        "line_count": candidate.line_count,
        "hunk_count": candidate.hunk_count,
        "tests_ok": candidate.tests_ok,
        "lint_ok": candidate.lint_ok,
        "types_ok": candidate.types_ok,
        "synth_ok": candidate.synth_ok,
        "coverage_delta": candidate.coverage_delta,
        "findings": list(candidate.findings),
        "attackers": dict(candidate.attackers),
        "counterfactuals": list(candidate.counterfactuals),
        "detail": candidate.detail,
    }


def candidate_from_payload(payload: dict[str, Any]) -> CandidateRecord:
    return CandidateRecord(
        identifier=str(payload.get("identifier", "")),
        status=str(payload.get("status", "proposed")),
        patch=str(payload.get("patch", "")),
        files_touched=tuple(str(item) for item in payload.get("files_touched", [])),
        strategy=str(payload.get("strategy", "")),
        seed=int(payload.get("seed", 0)),
        risk=float(payload.get("risk", 0.0)),
        score=float(payload.get("score", 0.0)),
        line_count=int(payload.get("line_count", 0)),
        hunk_count=int(payload.get("hunk_count", 0)),
        tests_ok=payload.get("tests_ok"),
        lint_ok=payload.get("lint_ok"),
        types_ok=payload.get("types_ok"),
        synth_ok=payload.get("synth_ok"),
        coverage_delta=float(payload.get("coverage_delta", 0.0)),
        findings=tuple(str(item) for item in payload.get("findings", [])),
        attackers={
            str(key): float(value)
            for key, value in dict(payload.get("attackers", {})).items()
        },
        counterfactuals=tuple(str(item) for item in payload.get("counterfactuals", [])),
        detail=str(payload.get("detail", "")),
    )


def request_payload(request: RunRequest) -> dict[str, Any]:
    return {
        "task_text": request.task_text,
        "files": list(request.files),
        "auto_loop": request.auto_loop,
        "apply_accepted": request.apply_accepted,
        "planner_enabled": request.planner_enabled,
        "redteam_enabled": request.redteam_enabled,
        "debug_enabled": request.debug_enabled,
        "mode_override": request.mode_override,
        "risk_threshold": request.risk_threshold,
        "context_level": request.context_level,
        "test_mode": request.test_mode,
    }


def build_client_from_request(
    request: RunRequest,
    *,
    runtime_probe: Callable[..., tuple[str | None, list[str]]] | None = None,
    model_selector: Callable[..., str | None] | None = None,
) -> tuple[OllamaClient | None, str]:
    probe = runtime_probe or detect_ollama_endpoint
    select_model = model_selector or choose_model
    endpoint, models = probe(preferred_url=request.preferred_url, timeout_s=5)
    model = select_model(models, preferred=request.preferred_model)
    summary = compact_runtime_summary(endpoint, model, models)
    if endpoint is None or model is None:
        return None, summary
    config = OllamaConfig(
        enabled=True,
        required=True,
        planner_enabled=request.planner_enabled,
        redteam_enabled=request.redteam_enabled,
        base_url=endpoint,
        executor_model=model,
        planner_model=model,
        redteam_model=model,
        timeout_s=request.timeout_s,
        num_ctx=request.num_ctx,
        temperature=0.2,
        top_p=0.9,
        base_seed=0,
    )
    return OllamaClient(config=config), summary


def runtime_block_message() -> str:
    return (
        "Forge could not find a ready Ollama runtime. "
        "Run `./forge --check`, then start Ollama or pull a coder model if needed."
    )


def runtime_doctor_message(runtime_summary: str) -> str:
    if "not detected" not in runtime_summary.lower():
        return runtime_summary
    return (
        "Runtime missing. Start Ollama with `ollama serve`, pull a coder model like "
        "`ollama pull qwen3-coder:30b`, then press Check Tools."
    )
