"""Shared operator controller for Forge UI surfaces."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Any, Callable

from ..runtime.config import (
    DEFAULT_CONTEXT_CONFIG,
    DEFAULT_UI_STATE_CONFIG,
    UiToolProfile,
)
from ..runtime.capabilities import CapabilityStatus, detect_capabilities
from ..transform.apply import (
    apply_unified_diff,
    extract_changed_files,
    reverse_unified_diff,
)
from .common import (
    CandidateRecord,
    HistoryRecord,
    PATCH_APPLY_ERROR,
    PATCH_REVERT_ERROR,
    RunRequest,
    artifacts_dir_for_repo,
    build_client_from_request,
    candidate_from_payload,
    candidate_payload,
    candidate_status,
    command_legend,
    event_status,
    example_tasks,
    find_history_index,
    history_record_from_result,
    load_history_records,
    quickstart_steps,
    record_diff_text,
    render_control_panel,
    render_files_panel,
    render_redteam_panel,
    render_status_strip,
    render_test_panel,
    request_payload,
    runtime_doctor_steps,
    selected_label,
    stage_label,
    status_from_result,
    task_identifier,
    tool_profiles,
    workflow_presets,
)
from .session import (
    AppliedDeltaRecord,
    default_machine_state,
    default_session_path,
    load_session,
    save_session,
)


class ForgeOperatorController:
    """Central source of truth for Forge operator state."""

    def __init__(
        self,
        repo_root: Path,
        *,
        preferred_model: str | None = None,
        preferred_url: str | None = None,
        timeout_s: int = 300,
        num_ctx: int = 2048,
        runtime_probe: Callable[..., tuple[str | None, list[str]]] | None = None,
        model_selector: Callable[..., str | None] | None = None,
        history_loader: Callable[..., list[HistoryRecord]] | None = None,
        client_builder: Callable[..., tuple[object | None, str]] | None = None,
        capability_detector: Callable[[Path], list[CapabilityStatus]] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.preferred_model = preferred_model
        self.preferred_url = preferred_url
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self.runtime_probe = runtime_probe
        self.model_selector = model_selector
        self.history_loader = history_loader
        self.client_builder = client_builder
        self.capability_detector = capability_detector
        self.session_path = default_session_path(repo_root)
        self.session = load_session(self.session_path)
        self.history: list[HistoryRecord] = []
        self.selected_record: HistoryRecord | None = None
        self.live_candidates: dict[str, CandidateRecord] = {
            candidate_id: candidate_from_payload(payload)
            for candidate_id, payload in self.session.live_candidates.items()
        }
        self.selected_candidate_id: str | None = self.session.selected_candidate_id
        self.logs: deque[str] = deque(
            self.session.logs, maxlen=DEFAULT_UI_STATE_CONFIG.max_logs
        )
        self.running = False
        self.stop_requested = False
        self.controls: dict[str, Any] = dict(self.session.controls)
        self.machine_state: dict[str, Any] = dict(default_machine_state())
        self.machine_state.update(self.session.machine_state)
        self.runtime_summary = self.session.runtime_summary
        self.applied_history: list[AppliedDeltaRecord] = list(
            self.session.applied_history
        )
        self.capabilities: list[CapabilityStatus] = []
        restored_logs = bool(self.logs)
        self.refresh_runtime(log_runtime=True)
        self.refresh_history()
        if not restored_logs:
            self.log("Forge ready. Type a task and press Start.")

    def refresh_runtime(self, *, log_runtime: bool = True) -> None:
        from ..models.discovery import (
            compact_runtime_summary,
            detect_ollama_endpoint,
            choose_model,
        )

        probe = self.runtime_probe or detect_ollama_endpoint
        select_model = self.model_selector or choose_model
        endpoint, models = probe(preferred_url=self.preferred_url, timeout_s=5)
        model = select_model(models, preferred=self.preferred_model)
        self.runtime_summary = compact_runtime_summary(endpoint, model, models)
        self.machine_state["runtime_endpoint"] = endpoint
        self.machine_state["runtime_model"] = model
        self.machine_state["runtime_models"] = models
        if endpoint is None or model is None:
            self.machine_state["status"] = "RUNTIME MISSING"
        elif self.machine_state.get("status") == "RUNTIME MISSING":
            self.machine_state["status"] = "WAITING"
            self.machine_state["stage_label"] = "idle"
        if log_runtime:
            self.log(self.runtime_summary)
        self.refresh_capabilities()

    def refresh_capabilities(self) -> None:
        detector = self.capability_detector or detect_capabilities
        self.capabilities = detector(self.repo_root)
        self.machine_state["capabilities"] = [
            item.as_dict() for item in self.capabilities
        ]

    def refresh_history(self) -> None:
        history_loader = self.history_loader or load_history_records
        self.history = history_loader(artifacts_dir_for_repo(self.repo_root))
        if self.history and self.selected_candidate_id is None:
            if self.session.selected_record_id is not None:
                index = find_history_index(
                    self.history, self.session.selected_record_id
                )
                self.selected_record = (
                    self.history[index] if index is not None else self.history[0]
                )
            elif self.selected_record is None:
                self.selected_record = self.history[0]
        if not self.history:
            self.selected_record = None

    def current_record(self) -> HistoryRecord | CandidateRecord | None:
        if self.selected_candidate_id is not None:
            candidate = self.live_candidates.get(self.selected_candidate_id)
            if candidate is not None:
                return candidate
        return self.selected_record

    def browser_snapshot(self) -> dict[str, Any]:
        record = self.current_record()
        return {
            "runtime_summary": self.runtime_summary,
            "status_strip": render_status_strip(
                self.runtime_summary,
                self.machine_state,
                live_count=len(self.live_candidates),
                history_count=len(self.history),
                selected_label=selected_label(record),
            ),
            "control_summary": render_control_panel(
                self.runtime_summary,
                self.machine_state,
                record,
                debug=bool(self.controls["debug"]),
            ),
            "files_panel_text": render_files_panel(record),
            "redteam_text": render_redteam_panel(record, expanded=True),
            "tests_text": render_test_panel(record, expanded=True),
            "diff_text": record_diff_text(record),
            "logs": list(self.logs),
            "task_text": self.session.task_text,
            "files_text": self.session.files_text,
            "live_candidates": [
                {
                    "id": candidate.identifier,
                    "label": candidate.label,
                    "status": candidate.status,
                    "selected": candidate.identifier == self.selected_candidate_id,
                }
                for candidate in self.live_candidates.values()
            ],
            "history": [
                {
                    "id": record.identifier,
                    "label": record.label,
                    "status": record.status,
                    "selected": self.selected_candidate_id is None
                    and self.selected_record is not None
                    and record.identifier == self.selected_record.identifier,
                }
                for record in self.history
            ],
            "controls": dict(self.controls),
            "quickstart": quickstart_steps(),
            "doctor": runtime_doctor_steps(self.runtime_summary),
            "applied_history": [item.as_dict() for item in self.applied_history],
            "legend": [
                {"command": command, "meaning": meaning}
                for command, meaning in command_legend()
            ],
            "example_tasks": example_tasks(),
            "workflow_presets": workflow_presets(),
            "tool_profiles": tool_profiles(),
            "capabilities": [item.as_dict() for item in self.capabilities],
            "selected_label": selected_label(record),
            "running": self.running,
        }

    def update_inputs(self, task_text: str, files_text: str) -> None:
        self.session.task_text = task_text
        self.session.files_text = files_text
        self.persist_session()

    def apply_controls(self, controls: dict[str, Any], *, auto: bool) -> None:
        self.controls["auto"] = auto
        self.controls["apply"] = bool(controls.get("apply", self.controls["apply"]))
        self.controls["planner"] = bool(
            controls.get("planner", self.controls["planner"])
        )
        self.controls["redteam"] = bool(
            controls.get("redteam", self.controls["redteam"])
        )
        self.controls["debug"] = bool(controls.get("debug", self.controls["debug"]))
        self.controls["mode_override"] = str(
            controls.get("mode_override", self.controls["mode_override"])
        ).upper()
        self.controls["risk_threshold"] = float(
            controls.get("risk_threshold", self.controls["risk_threshold"])
        )
        self.controls["context_level"] = int(
            controls.get(
                "context_level",
                self.controls.get(
                    "context_level", DEFAULT_UI_STATE_CONFIG.context_level
                ),
            )
        )
        self.controls["test_mode"] = str(
            controls.get(
                "test_mode",
                self.controls.get("test_mode", DEFAULT_UI_STATE_CONFIG.test_mode),
            )
        )
        self.controls["tool_profile"] = str(
            controls.get(
                "tool_profile",
                self.controls.get("tool_profile", DEFAULT_UI_STATE_CONFIG.tool_profile),
            )
        )
        self.machine_state["risk_threshold"] = self.controls["risk_threshold"]
        self.machine_state["mode_override"] = self.controls["mode_override"]
        self.machine_state["mode"] = self.controls["mode_override"]
        self.machine_state["context_level"] = self.controls["context_level"]
        self.machine_state["test_mode"] = self.controls["test_mode"]
        self.machine_state["tool_profile"] = self.controls["tool_profile"]

    def request_stop(self) -> None:
        self.stop_requested = True
        self.machine_state["status"] = "RUNNING"
        self.machine_state["stage_label"] = "stop requested"
        self.machine_state["last_event"] = "stop requested"
        self.persist_session()
        self.log("Stop requested. Forge will stop after the current iteration.")

    def build_request(
        self, task_text: str, files: tuple[str, ...], *, auto: bool
    ) -> RunRequest | None:
        if not task_text:
            self.log("Type a task first, like: fix the failing tests")
            return None
        return RunRequest(
            task_text=task_text,
            files=files,
            repo_root=self.repo_root,
            apply_accepted=bool(self.controls["apply"]),
            planner_enabled=bool(self.controls["planner"]),
            redteam_enabled=bool(self.controls["redteam"]),
            debug_enabled=bool(self.controls["debug"]),
            auto_loop=auto,
            mode_override=str(self.controls["mode_override"]),
            risk_threshold=float(self.controls["risk_threshold"]),
            context_level=int(self.controls["context_level"]),
            test_mode=str(self.controls["test_mode"]),
            timeout_s=self.timeout_s,
            num_ctx=self.num_ctx,
            preferred_model=self.preferred_model,
            preferred_url=self.preferred_url,
        )

    def queue_request(self, request: RunRequest) -> None:
        self.live_candidates = {}
        self.selected_candidate_id = None
        self.machine_state["task"] = request.task_text
        self.machine_state["stage"] = "queued"
        self.machine_state["stage_label"] = "queued"
        self.machine_state["status"] = "RUNNING"
        self.machine_state["branch_count"] = 0
        self.machine_state["last_event"] = "queued"
        self.machine_state["context_level"] = request.context_level
        self.machine_state["test_mode"] = request.test_mode
        self.session.task_text = request.task_text
        self.session.files_text = " ".join(request.files)
        self.session.resume_request = request_payload(request)
        self.persist_session()

    def build_resume_request(self) -> RunRequest | None:
        payload = dict(self.session.resume_request or {})
        if not payload:
            self.log("No paused task is ready to resume yet.")
            return None
        self.apply_controls(payload, auto=bool(payload.get("auto_loop", False)))
        return self.build_request(
            str(payload.get("task_text", "")),
            tuple(str(item) for item in payload.get("files", [])),
            auto=bool(payload.get("auto_loop", False)),
        )

    def build_client(self, request: RunRequest):
        builder = self.client_builder or build_client_from_request
        return builder(
            request,
            runtime_probe=self.runtime_probe,
            model_selector=self.model_selector,
        )

    def set_mode_override(self, value: str) -> bool:
        mapping = {
            "auto": "AUTO",
            "simple": "SIMPLE",
            "bi": "BISECT",
            "bisect": "BISECT",
            "tri": "TRISECT",
            "trisect": "TRISECT",
        }
        if value not in mapping:
            self.log("Mode must be auto, simple, bi, or tri.")
            return False
        self.controls["mode_override"] = mapping[value]
        self.machine_state["mode_override"] = mapping[value]
        self.machine_state["mode"] = mapping[value]
        self.persist_session()
        self.log(f"Mode override: {mapping[value]}")
        return True

    def set_tau(self, value: str) -> bool:
        try:
            parsed = max(0.0, min(1.0, float(value)))
        except ValueError:
            self.log("Tau must be a number between 0 and 1.")
            return False
        self.controls["risk_threshold"] = parsed
        self.machine_state["risk_threshold"] = parsed
        self.persist_session()
        self.log(f"Risk threshold set to {parsed:.2f}")
        return True

    def set_flag(self, name: str, enabled: bool, label: str) -> None:
        self.controls[name] = enabled
        self.persist_session()
        self.log(f"{label} {'on' if enabled else 'off'}")

    def adjust_context(self, delta: int) -> bool:
        current = int(
            self.controls.get("context_level", DEFAULT_UI_STATE_CONFIG.context_level)
        )
        updated = max(
            0, min(DEFAULT_UI_STATE_CONFIG.max_context_level, current + delta)
        )
        if updated == current:
            self.log(f"Context already at level {current}.")
            return False
        self.controls["context_level"] = updated
        self.machine_state["context_level"] = updated
        self.persist_session()
        self.log(
            "Context level "
            f"{updated}: up to {DEFAULT_CONTEXT_CONFIG.target_budget(updated)} files, "
            f"excerpt budget {DEFAULT_CONTEXT_CONFIG.excerpt_limit(updated)} chars."
        )
        return True

    def set_test_mode(self, value: str) -> bool:
        if value not in {"default", "fast", "full"}:
            self.log("Test mode must be default, fast, or full.")
            return False
        self.controls["test_mode"] = value
        self.machine_state["test_mode"] = value
        self.persist_session()
        self.log(
            "Test mode fast: Forge will target explicit test files when possible."
            if value == "fast"
            else f"Test mode {value} enabled."
        )
        return True

    def set_tool_profile(self, value: str) -> bool:
        profile = _find_tool_profile(value)
        if profile is None:
            self.log("Unknown tool style.")
            return False
        self.controls["tool_profile"] = profile.identifier
        self.controls["mode_override"] = profile.mode_override
        self.controls["context_level"] = profile.context_level
        self.controls["test_mode"] = profile.test_mode
        self.controls["auto"] = profile.auto_loop
        self.controls["planner"] = profile.planner_enabled
        self.controls["redteam"] = profile.redteam_enabled
        self.machine_state.update(
            {
                "tool_profile": profile.identifier,
                "mode_override": profile.mode_override,
                "mode": profile.mode_override,
                "context_level": profile.context_level,
                "test_mode": profile.test_mode,
            }
        )
        self.persist_session()
        self.log(f"Tool style: {profile.label}")
        return True

    def select_candidate(self, candidate_id: str) -> None:
        if candidate_id in self.live_candidates:
            self.selected_candidate_id = candidate_id
            self.selected_record = None
            self.session.selected_candidate_id = candidate_id
            self.session.selected_record_id = None
            self.persist_session()

    def select_history(self, record_id: str) -> None:
        for record in self.history:
            if record.identifier == record_id:
                self.selected_candidate_id = None
                self.selected_record = record
                self.session.selected_candidate_id = None
                self.session.selected_record_id = record.identifier
                self.persist_session()
                return

    def accept_selected_patch(self) -> tuple[bool, str | None]:
        if (
            self.selected_candidate_id is not None
            and self.selected_candidate_id in self.live_candidates
        ):
            candidate = self.live_candidates[self.selected_candidate_id]
            patch = candidate.patch
            label = f"live candidate {candidate.identifier}"
            patch_path = None
            identifier = candidate.identifier
        elif (
            self.selected_record is not None
            and self.selected_record.patch_path is not None
        ):
            if bool(self.selected_record.payload.get("applied")):
                self.log("That patch was already applied.")
                return False, "already applied"
            patch = self.selected_record.diff_text
            label = f"patch {self.selected_record.patch_path}"
            patch_path = str(self.selected_record.patch_path)
            identifier = self.selected_record.identifier
        else:
            self.log("No accepted patch is selected.")
            return False, "missing selection"
        try:
            apply_unified_diff(self.repo_root, patch)
        except ValueError as exc:
            self.log(f"Could not apply patch: {exc}")
            return False, PATCH_APPLY_ERROR
        self.remember_applied_patch(
            label=label,
            patch=patch,
            files_touched=extract_changed_files(patch),
            source="operator_accept",
            task=str(self.machine_state.get("task", "")),
            identifier=identifier,
            patch_path=patch_path,
        )
        self.log(f"Applied {label}")
        return True, None

    def reject_selection(self) -> None:
        if (
            self.selected_candidate_id is not None
            and self.selected_candidate_id in self.live_candidates
        ):
            rejected = self.selected_candidate_id
            del self.live_candidates[rejected]
            self.selected_candidate_id = next(iter(self.live_candidates), None)
            self.log(f"Rejected live candidate {rejected}.")
        else:
            self.selected_record = None
            self.log("Reject cleared the current selection.")
        self.persist_session()

    def preview_safe_revert(self) -> bool:
        if not self.applied_history:
            self.log("Nothing in Forge lineage is ready to revert.")
            return False
        latest = self.applied_history[-1]
        touched = ", ".join(latest.files_touched[:4]) or "unknown files"
        self.log(
            f"Ready to revert {latest.label} touching {touched}. Run `revert apply` to undo it."
        )
        return True

    def apply_safe_revert(self) -> tuple[bool, str | None]:
        if not self.applied_history:
            self.log("Nothing in Forge lineage is ready to revert.")
            return False, "nothing to revert"
        latest = self.applied_history[-1]
        try:
            apply_unified_diff(self.repo_root, latest.revert_patch)
        except ValueError as exc:
            self.log(f"Could not revert {latest.label}: {exc}")
            return False, PATCH_REVERT_ERROR
        self.applied_history.pop()
        self.machine_state["status"] = "WAITING"
        self.machine_state["stage_label"] = "reverted"
        self.machine_state["last_event"] = f"reverted {latest.identifier}"
        self.persist_session()
        self.log(f"Reverted {latest.label}")
        return True, None

    def remember_applied_patch(
        self,
        *,
        label: str,
        patch: str,
        files_touched: tuple[str, ...],
        source: str,
        task: str,
        identifier: str,
        patch_path: str | None = None,
    ) -> None:
        entry = AppliedDeltaRecord(
            identifier=identifier or task_identifier(label),
            label=label,
            task=task,
            source=source,
            patch_text=patch,
            revert_patch=reverse_unified_diff(patch),
            files_touched=tuple(files_touched),
            patch_path=patch_path,
        )
        if (
            self.applied_history
            and self.applied_history[-1].identifier == entry.identifier
        ):
            return
        self.applied_history.append(entry)
        self.applied_history = self.applied_history[
            -DEFAULT_UI_STATE_CONFIG.max_applied :
        ]
        self.persist_session()

    def handle_event(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage", "event"))
        self.machine_state["last_event"] = str(event.get("message", stage))
        self.machine_state["stage"] = stage
        self.machine_state["stage_label"] = stage_label(stage)
        self.machine_state["status"] = event_status(
            stage, event, current=str(self.machine_state.get("status", "WAITING"))
        )
        if "phi" in event:
            self.machine_state["phi"] = float(event["phi"])
        for key in ("qts", "h", "g", "r", "d"):
            if key in event:
                self.machine_state[key] = float(event[key])
        if "mode" in event:
            self.machine_state["mode"] = str(event["mode"])
        if "context_level" in event:
            self.machine_state["context_level"] = int(event["context_level"])
        if "test_mode" in event:
            self.machine_state["test_mode"] = str(event["test_mode"])
        if "candidates" in event:
            self.machine_state["branch_count"] = len(list(event["candidates"]))
        self._update_candidate_from_event(stage, event)
        self.machine_state["branch_count"] = max(
            int(self.machine_state.get("branch_count", 0)), len(self.live_candidates)
        )
        self.log(f"[{stage}] {event.get('message', '')}")

    def record_result(self, result: dict[str, Any]) -> HistoryRecord:
        record = history_record_from_result(result)
        self.selected_record = record
        self.session.selected_record_id = record.identifier
        self.machine_state["status"] = status_from_result(result)
        self.machine_state["stage"] = "complete"
        self.machine_state["stage_label"] = (
            "commit ready" if result["status"] == "promote" else result["status"]
        )
        self.machine_state["phi"] = float(result.get("phi", 0.0))
        self.machine_state["mode"] = str(result.get("mode", "AUTO"))
        self.machine_state["r"] = float(result.get("risk", 0.0))
        self.machine_state["ban_hits"] = int(
            result.get("metrics", {}).get("ban_hits", 0)
        )
        self.machine_state["last_event"] = str(result.get("detail", "completed"))
        self.machine_state["context_level"] = int(
            result.get("metrics", {}).get(
                "context_level", self.machine_state.get("context_level", 0)
            )
        )
        self.machine_state["test_mode"] = str(
            result.get("metrics", {}).get(
                "test_mode",
                self.machine_state.get("test_mode", DEFAULT_UI_STATE_CONFIG.test_mode),
            )
        )
        self.session.last_result_artifacts = {
            str(key): str(value)
            for key, value in dict(result.get("artifacts", {})).items()
        }
        self.refresh_history()
        delta_id = str(result.get("delta_id") or "")
        if delta_id and delta_id in self.live_candidates:
            self.selected_candidate_id = delta_id
            self.session.selected_candidate_id = delta_id
        elif self.selected_record is not None:
            self.session.selected_record_id = self.selected_record.identifier
        if bool(result.get("applied")) and record.diff_text.startswith("diff --git "):
            self.remember_applied_patch(
                label=f"auto-applied {record.identifier}",
                patch=record.diff_text,
                files_touched=record.files_touched,
                source="auto_apply",
                task=str(self.machine_state.get("task", "")),
                identifier=delta_id or record.identifier,
                patch_path=str(record.patch_path)
                if record.patch_path is not None
                else None,
            )
        self.log(f"{result['status']}: {result['detail']}")
        return record

    def set_running_state(self, running: bool) -> None:
        self.running = running
        if running:
            self.machine_state["status"] = "RUNNING"
            self.machine_state["stage_label"] = "running"
        elif self.machine_state.get("status") == "RUNNING":
            self.machine_state["status"] = "WAITING"
            if self.machine_state.get("stage") in {"queued", "idle"}:
                self.machine_state["stage_label"] = "idle"
        self.persist_session()

    def set_stage(self, status: str, label: str) -> None:
        self.machine_state["status"] = status
        self.machine_state["stage_label"] = label
        self.machine_state["last_event"] = label
        self.persist_session()

    def session_snapshot(self) -> dict[str, Any]:
        return {
            "runtime_summary": self.runtime_summary,
            "machine_state": dict(self.machine_state),
            "controls": dict(self.controls),
            "task_text": self.session.task_text,
            "files_text": self.session.files_text,
            "selected_result": self.selected_record.payload
            if self.selected_record is not None
            else None,
            "selected_candidate_id": self.selected_candidate_id,
            "selected_record_id": self.selected_record.identifier
            if self.selected_record is not None
            else None,
            "live_candidates": {
                candidate_id: candidate_payload(candidate)
                for candidate_id, candidate in self.live_candidates.items()
            },
            "logs": list(self.logs),
            "applied_history": [item.as_dict() for item in self.applied_history],
            "resume_request": self.session.resume_request,
        }

    def export_snapshot(self, export_path: Path) -> Path:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            json.dumps(self.session_snapshot(), indent=2), encoding="utf-8"
        )
        self.log(f"Exported UI state to {export_path}")
        return export_path

    def persist_session(self) -> None:
        if not self.session.task_text:
            self.session.task_text = str(self.machine_state.get("task", ""))
        self.session.controls = dict(self.controls)
        self.session.machine_state = dict(self.machine_state)
        self.session.runtime_summary = self.runtime_summary
        self.session.selected_candidate_id = self.selected_candidate_id
        self.session.selected_record_id = (
            self.selected_record.identifier
            if self.selected_record is not None
            else None
        )
        self.session.live_candidates = {
            candidate_id: candidate_payload(candidate)
            for candidate_id, candidate in self.live_candidates.items()
        }
        self.session.logs = list(self.logs)
        self.session.applied_history = list(self.applied_history)
        save_session(self.session_path, self.session)

    def log(self, message: str) -> None:
        self.logs.append(message)
        self.persist_session()

    def _update_candidate_from_event(self, stage: str, event: dict[str, Any]) -> None:
        candidate_id = event.get("candidate_id")
        if not candidate_id:
            if stage == "decision":
                delta_id = event.get("delta_id")
                if isinstance(delta_id, str) and delta_id in self.live_candidates:
                    candidate = self.live_candidates[delta_id]
                    self.live_candidates[delta_id] = CandidateRecord(
                        **{
                            **candidate.__dict__,
                            "status": "accepted"
                            if event.get("status") == "promote"
                            else candidate.status,
                            "detail": str(event.get("detail", candidate.detail)),
                            "risk": float(event.get("risk", candidate.risk)),
                        }
                    )
            return
        candidate = self.live_candidates.get(
            str(candidate_id), CandidateRecord(identifier=str(candidate_id))
        )
        attackers = dict(candidate.attackers)
        attackers.update(
            {
                str(name): float(value)
                for name, value in dict(event.get("attackers", {})).items()
            }
        )
        updated = CandidateRecord(
            identifier=candidate.identifier,
            status=candidate_status(stage, candidate.status),
            patch=str(event.get("patch", candidate.patch)),
            files_touched=tuple(event.get("files_touched", candidate.files_touched)),
            strategy=str(event.get("strategy", candidate.strategy)),
            seed=int(event.get("seed", candidate.seed)),
            risk=float(event.get("risk", candidate.risk)),
            score=float(event.get("score", candidate.score)),
            line_count=int(event.get("line_count", candidate.line_count)),
            hunk_count=int(event.get("hunk_count", candidate.hunk_count)),
            tests_ok=event.get("tests_ok", candidate.tests_ok),
            lint_ok=event.get("lint_ok", candidate.lint_ok),
            types_ok=event.get("types_ok", candidate.types_ok),
            synth_ok=event.get("synth_ok", candidate.synth_ok),
            coverage_delta=float(event.get("coverage_delta", candidate.coverage_delta)),
            findings=tuple(event.get("findings", candidate.findings)),
            attackers=attackers,
            counterfactuals=tuple(
                event.get("counterfactuals", candidate.counterfactuals)
            ),
            detail=str(event.get("detail", event.get("message", candidate.detail))),
        )
        self.live_candidates[updated.identifier] = updated
        if self.selected_candidate_id is None:
            self.selected_candidate_id = updated.identifier


def _find_tool_profile(identifier: str) -> UiToolProfile | None:
    for profile in DEFAULT_UI_STATE_CONFIG.tool_profiles:
        if profile.identifier == identifier:
            return profile
    return None
