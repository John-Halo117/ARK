"""Browser-based Forge operator app."""

from __future__ import annotations

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
import webbrowser

from ..core.orchestrator import ForgeOrchestrator
from ..models.discovery import (
    compact_runtime_summary,
    detect_ollama_endpoint,
    choose_model,
)
from ..models.ollama_client import OllamaClient, OllamaConfig
from ..runtime.config import DEFAULT_UI_STATE_CONFIG
from ..transform.apply import (
    apply_unified_diff,
    extract_changed_files,
    reverse_unified_diff,
)
from ..types import ForgeTask
from .controller import ForgeOperatorController
from .app import (
    CandidateRecord,
    HistoryRecord,
    RunRequest,
    _build_client_from_request,
    _candidate_from_payload,
    _candidate_payload,
    _event_status,
    _record_diff_text,
    _request_payload,
    _runtime_doctor_message,
    _selected_label,
    _stage_label,
    _status_from_result,
    _task_identifier,
    artifacts_dir_for_repo,
    command_legend,
    example_tasks,
    history_record_from_result,
    load_history_records,
    render_control_panel,
    render_files_panel,
    render_redteam_panel,
    render_status_strip,
    render_test_panel,
    tool_profiles,
    workflow_presets,
)
from .common import (
    PATCH_APPLY_ERROR,
    PATCH_REVERT_ERROR,
    parse_command as _parse_command,
)
from .session import (
    AppliedDeltaRecord,
    default_machine_state,
    default_session_path,
    load_session,
    save_session,
)

DEFAULT_BROWSER_PORT = DEFAULT_UI_STATE_CONFIG.default_browser_port


class BrowserState:
    """Thin browser wrapper over the shared Forge operator controller."""

    def __init__(
        self,
        repo_root: Path,
        *,
        preferred_model: str | None = None,
        preferred_url: str | None = None,
        timeout_s: int = 300,
        num_ctx: int = 2048,
    ) -> None:
        self.server: ThreadingHTTPServer | None = None
        self._lock = threading.RLock()
        restored_logs = bool(load_session(default_session_path(repo_root)).logs)
        self.controller = ForgeOperatorController(
            repo_root,
            preferred_model=preferred_model,
            preferred_url=preferred_url,
            timeout_s=timeout_s,
            num_ctx=num_ctx,
            runtime_probe=detect_ollama_endpoint,
            model_selector=choose_model,
            history_loader=load_history_records,
        )
        if not restored_logs:
            self.controller.log("Forge browser app ready. Type a task and press Start.")

    def attach_server(self, server: ThreadingHTTPServer) -> None:
        self.server = server

    def refresh_runtime(self) -> None:
        with self._lock:
            self.controller.refresh_runtime()

    def refresh_history(self) -> None:
        with self._lock:
            self.controller.refresh_history()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.controller.browser_snapshot()

    def handle_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "")).strip().lower()
        if action == "run":
            return self.start_run(
                payload, auto=bool(payload.get("controls", {}).get("auto", False))
            )
        if action == "step":
            return self.start_run(payload, auto=False)
        if action == "stop":
            with self._lock:
                self.controller.request_stop()
            return {"ok": True}
        if action == "check_runtime":
            self.refresh_runtime()
            return {"ok": True}
        if action == "accept":
            return self.accept_selected_patch()
        if action == "reject":
            return self.reject_selection()
        if action == "export":
            return self.export_state()
        if action == "command":
            return self.handle_command(payload)
        if action == "select_candidate":
            self.select_candidate(str(payload.get("id", "")))
            return {"ok": True}
        if action == "select_history":
            self.select_history(str(payload.get("id", "")))
            return {"ok": True}
        if action == "set_tool_profile":
            return self._locked_result(
                self.controller.set_tool_profile,
                str(payload.get("id", "")),
                error="invalid tool style",
            )
        if action == "shutdown":
            with self._lock:
                self.controller.log("Shutting down Forge browser app.")
            threading.Thread(target=self.shutdown_server, daemon=True).start()
            return {"ok": True}
        return {"ok": False, "error": f"unknown action: {action}"}

    def start_run(self, payload: dict[str, Any], *, auto: bool) -> dict[str, Any]:
        task_text = str(payload.get("task", "")).strip()
        files_text = str(payload.get("files", ""))
        files = tuple(_split_files(files_text))
        with self._lock:
            if self.controller.running:
                self.controller.log("Forge is already running.")
                return {"ok": False, "error": "already running"}
            self.controller.update_inputs(task_text, files_text)
            self.controller.apply_controls(dict(payload.get("controls", {})), auto=auto)
            request = self.controller.build_request(task_text, files, auto=auto)
            if request is None:
                return {"ok": False, "error": "missing task"}
            self.controller.queue_request(request)
        threading.Thread(target=self._run_worker, args=(request,), daemon=True).start()
        return {"ok": True}

    def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.controller.update_inputs(
                str(payload.get("task", self.controller.session.task_text)),
                str(payload.get("files", self.controller.session.files_text)),
            )
        parsed = _parse_command(str(payload.get("command", "")))
        if parsed is None:
            return {"ok": False, "error": "missing command"}
        raw, cmd, args = parsed
        immediate = self._dispatch_immediate_command(cmd, args, payload)
        if immediate is not None:
            return immediate
        settings = self._dispatch_setting_command(cmd, args)
        if settings is not None:
            return settings
        with self._lock:
            self.controller.log(f"Unknown command: {raw}")
        return {"ok": False, "error": "unknown command"}

    def _dispatch_immediate_command(
        self, cmd: str, args: list[str], payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        if cmd == "run":
            return self.start_run(payload, auto=True)
        if cmd == "step":
            return self.start_run(payload, auto=False)
        if cmd == "resume":
            return self.resume_last_request()
        if cmd == "stop":
            return self.handle_action({"action": "stop"})
        if cmd == "accept":
            return self.accept_selected_patch()
        if cmd == "reject":
            return self.reject_selection()
        if cmd == "revert":
            return (
                self.apply_safe_revert()
                if args and args[0] == "apply"
                else self.preview_safe_revert()
            )
        if cmd == "export":
            return self.export_state()
        if cmd == "quit":
            return self.handle_action({"action": "shutdown"})
        return None

    def _dispatch_setting_command(
        self, cmd: str, args: list[str]
    ) -> dict[str, Any] | None:
        if cmd == "mode" and args:
            return self._locked_result(
                self.controller.set_mode_override, args[0], error="invalid mode"
            )
        if cmd == "plan" and args:
            return self._locked_toggle("planner", args[0] == "on", "Planner")
        if cmd == "tau" and args:
            return self._locked_result(
                self.controller.set_tau, args[0], error="invalid tau"
            )
        if cmd == "redteam" and args:
            return self._locked_toggle("redteam", args[0] == "on", "Model redteam")
        if cmd == "tests" and args:
            return self._locked_result(
                self.controller.set_test_mode, args[0], error="invalid test mode"
            )
        if cmd in {"expand", "shrink"}:
            delta = 1 if cmd == "expand" else -1
            return self._locked_result(
                self.controller.adjust_context, delta, error="context unchanged"
            )
        if cmd == "debug" and args:
            return self._locked_toggle("debug", args[0] == "on", "Debug")
        return None

    def _locked_toggle(self, name: str, enabled: bool, label: str) -> dict[str, Any]:
        with self._lock:
            self.controller.set_flag(name, enabled, label)
        return {"ok": True}

    def _locked_result(self, action, arg, *, error: str) -> dict[str, Any]:
        with self._lock:
            ok = action(arg)
        return {"ok": ok, **({"error": error} if not ok else {})}

    def select_candidate(self, candidate_id: str) -> None:
        with self._lock:
            self.controller.select_candidate(candidate_id)

    def select_history(self, record_id: str) -> None:
        with self._lock:
            self.controller.select_history(record_id)

    def accept_selected_patch(self) -> dict[str, Any]:
        with self._lock:
            ok, error = self.controller.accept_selected_patch()
        return {"ok": ok, **({"error": error} if error else {})}

    def reject_selection(self) -> dict[str, Any]:
        with self._lock:
            self.controller.reject_selection()
        return {"ok": True}

    def export_state(self) -> dict[str, Any]:
        export_path = self.controller.repo_root / ".forge" / "ui-export.json"
        with self._lock:
            path = self.controller.export_snapshot(export_path)
        return {"ok": True, "path": str(path)}

    def resume_last_request(self) -> dict[str, Any]:
        with self._lock:
            if self.controller.running:
                self.controller.log("Forge is already running.")
                return {"ok": False, "error": "already running"}
            request = self.controller.build_resume_request()
            if request is None:
                return {"ok": False, "error": "missing resume request"}
            self.controller.queue_request(request)
        threading.Thread(target=self._run_worker, args=(request,), daemon=True).start()
        return {"ok": True}

    def preview_safe_revert(self) -> dict[str, Any]:
        with self._lock:
            ok = self.controller.preview_safe_revert()
        return {"ok": ok, **({"error": "nothing to revert"} if not ok else {})}

    def apply_safe_revert(self) -> dict[str, Any]:
        with self._lock:
            ok, error = self.controller.apply_safe_revert()
        return {"ok": ok, **({"error": error} if error else {})}

    def _remember_applied_patch(
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
        with self._lock:
            self.controller.remember_applied_patch(
                label=label,
                patch=patch,
                files_touched=files_touched,
                source=source,
                task=task,
                identifier=identifier,
                patch_path=patch_path,
            )

    def shutdown_server(self) -> None:
        if self.server is not None:
            time.sleep(0.15)
            self.server.shutdown()

    def _run_worker(self, request: RunRequest) -> None:
        attempts = 0
        max_attempts = (
            DEFAULT_UI_STATE_CONFIG.auto_loop_attempts if request.auto_loop else 1
        )
        with self._lock:
            self.controller.stop_requested = False
            self.controller.set_running_state(True)
        while attempts < max_attempts:
            with self._lock:
                if self.controller.stop_requested:
                    break
            attempts += 1
            result = self._run_attempt(request, attempts)
            if result is None:
                break
            with self._lock:
                self.controller.record_result(result)
            if not request.auto_loop or result["status"] in {
                "promote",
                "manual_review",
            }:
                break
        with self._lock:
            self.controller.set_running_state(False)
            if self.controller.stop_requested:
                self.controller.set_stage("INTERRUPTED", "interrupted")
                self.controller.log("Forge stopped by operator.")

    def _run_attempt(
        self, request: RunRequest, attempt: int
    ) -> dict[str, object] | None:
        with self._lock:
            self.controller.set_stage("RUNNING", f"iter {attempt}")
        client, runtime_summary = self._build_client(request)
        with self._lock:
            self.controller.runtime_summary = runtime_summary
            self.controller.persist_session()
        if client is None:
            with self._lock:
                self.controller.set_stage("RUNTIME MISSING", "runtime unavailable")
                self.controller.log(_runtime_doctor_message(runtime_summary))
            return None
        try:
            return self._process_request(request, client)
        except Exception as exc:  # pragma: no cover - safety net for interactive mode
            with self._lock:
                self.controller.set_stage("BLOCKED", str(exc))
                self.controller.log(f"Run failed: {exc}")
            return None

    def _process_request(
        self, request: RunRequest, client: OllamaClient
    ) -> dict[str, object]:
        orchestrator = ForgeOrchestrator(
            self.controller.repo_root,
            apply_accepted=request.apply_accepted,
            client=client,
        )
        task = ForgeTask(
            identifier=_task_identifier(request.task_text),
            summary=request.task_text,
            scope="S1",
            todo="T1",
            target_files=request.files,
            context_level=request.context_level,
            test_mode=request.test_mode,
        )
        return orchestrator.process(
            task,
            dry_run=False,
            mode_override=None
            if request.mode_override == "AUTO"
            else request.mode_override,
            risk_threshold=request.risk_threshold,
            event_sink=self._event_sink,
        )

    def _event_sink(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.controller.handle_event(payload)

    def _build_client(self, request: RunRequest) -> tuple[OllamaClient | None, str]:
        endpoint, models = detect_ollama_endpoint(
            preferred_url=request.preferred_url, timeout_s=5
        )
        model = choose_model(models, preferred=request.preferred_model)
        summary = compact_runtime_summary(endpoint, model, models)
        if endpoint is None or model is None:
            return None, summary
        return (
            OllamaClient(
                config=OllamaConfig(
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
            ),
            summary,
        )


class _LegacyBrowserState:
    """Shared mutable state for the Forge browser app."""

    def __init__(
        self,
        repo_root: Path,
        *,
        preferred_model: str | None = None,
        preferred_url: str | None = None,
        timeout_s: int = 300,
        num_ctx: int = 2048,
    ) -> None:
        self.repo_root = repo_root
        self.preferred_model = preferred_model
        self.preferred_url = preferred_url
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self.session_path = default_session_path(repo_root)
        self.session = load_session(self.session_path)
        self.history: list[HistoryRecord] = []
        self.selected_record: HistoryRecord | None = None
        self.live_candidates: dict[str, CandidateRecord] = {
            candidate_id: _candidate_from_payload(payload)
            for candidate_id, payload in self.session.live_candidates.items()
        }
        self.selected_candidate_id: str | None = self.session.selected_candidate_id
        self.logs: deque[str] = deque(self.session.logs, maxlen=500)
        self.running = False
        self.stop_requested = False
        self.server: ThreadingHTTPServer | None = None
        self._lock = threading.RLock()
        self.controls: dict[str, Any] = dict(self.session.controls)
        self.machine_state: dict[str, Any] = dict(default_machine_state())
        self.machine_state.update(self.session.machine_state)
        self.runtime_summary = self.session.runtime_summary
        self.applied_history: list[AppliedDeltaRecord] = list(
            self.session.applied_history
        )
        restored_logs = bool(self.logs)
        self.refresh_runtime()
        self.refresh_history()
        if not restored_logs:
            self._log("Forge browser app ready. Type a task and press Start.")

    def attach_server(self, server: ThreadingHTTPServer) -> None:
        """Attach the backing HTTP server so the app can shut itself down."""

        self.server = server

    def refresh_runtime(self) -> None:
        """Refresh the detected Ollama runtime."""

        endpoint, models = detect_ollama_endpoint(
            preferred_url=self.preferred_url, timeout_s=5
        )
        model = choose_model(models, preferred=self.preferred_model)
        summary = compact_runtime_summary(endpoint, model, models)
        with self._lock:
            self.runtime_summary = summary
            self.machine_state["runtime_endpoint"] = endpoint
            self.machine_state["runtime_model"] = model
            self.machine_state["runtime_models"] = models
            if endpoint is None or model is None:
                self.machine_state["status"] = "RUNTIME MISSING"
            elif self.machine_state.get("status") == "RUNTIME MISSING":
                self.machine_state["status"] = "WAITING"
                self.machine_state["stage_label"] = "idle"
            self._log(summary)

    def refresh_history(self) -> None:
        """Reload persisted Forge runs."""

        with self._lock:
            self.history = load_history_records(artifacts_dir_for_repo(self.repo_root))
            if self.history and self.selected_candidate_id is None:
                if self.session.selected_record_id is not None:
                    match = next(
                        (
                            item
                            for item in self.history
                            if item.identifier == self.session.selected_record_id
                        ),
                        None,
                    )
                    self.selected_record = match or self.history[0]
                elif self.selected_record is None:
                    self.selected_record = self.history[0]
            if not self.history:
                self.selected_record = None

    def snapshot(self) -> dict[str, Any]:
        """Return the current browser snapshot."""

        with self._lock:
            record = self._current_record()
            return {
                "runtime_summary": self.runtime_summary,
                "status_strip": render_status_strip(
                    self.runtime_summary,
                    self.machine_state,
                    live_count=len(self.live_candidates),
                    history_count=len(self.history),
                    selected_label=_selected_label(record),
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
                "diff_text": _record_diff_text(record),
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
                "selected_label": _selected_label(record),
                "running": self.running,
            }

    def handle_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route one browser action."""

        action = str(payload.get("action", "")).strip().lower()
        if action == "run":
            return self.start_run(
                payload, auto=bool(payload.get("controls", {}).get("auto", False))
            )
        if action == "step":
            return self.start_run(payload, auto=False)
        if action == "stop":
            with self._lock:
                self.stop_requested = True
                self.machine_state["status"] = "RUNNING"
                self.machine_state["stage_label"] = "stop requested"
                self._log(
                    "Stop requested. Forge will stop after the current iteration."
                )
            return {"ok": True}
        if action == "check_runtime":
            self.refresh_runtime()
            return {"ok": True}
        if action == "accept":
            return self.accept_selected_patch()
        if action == "reject":
            return self.reject_selection()
        if action == "export":
            return self.export_state()
        if action == "command":
            return self.handle_command(payload)
        if action == "select_candidate":
            self.select_candidate(str(payload.get("id", "")))
            return {"ok": True}
        if action == "select_history":
            self.select_history(str(payload.get("id", "")))
            return {"ok": True}
        if action == "shutdown":
            self._log("Shutting down Forge browser app.")
            threading.Thread(target=self.shutdown_server, daemon=True).start()
            return {"ok": True}
        return {"ok": False, "error": f"unknown action: {action}"}

    def start_run(self, payload: dict[str, Any], *, auto: bool) -> dict[str, Any]:
        """Start a new Forge run in the background."""

        task_text = str(payload.get("task", "")).strip()
        files = _split_files(str(payload.get("files", "")))
        with self._lock:
            if self.running:
                self._log("Forge is already running.")
                return {"ok": False, "error": "already running"}
            if not task_text:
                self._log("Type a task first, like: fix the failing tests")
                return {"ok": False, "error": "missing task"}
            self._apply_controls(dict(payload.get("controls", {})), auto=auto)
            request = RunRequest(
                task_text=task_text,
                files=tuple(files),
                repo_root=self.repo_root,
                apply_accepted=bool(self.controls["apply"]),
                planner_enabled=bool(self.controls["planner"]),
                redteam_enabled=bool(self.controls["redteam"]),
                debug_enabled=bool(self.controls["debug"]),
                auto_loop=bool(self.controls["auto"]),
                mode_override=str(self.controls["mode_override"]),
                risk_threshold=float(self.controls["risk_threshold"]),
                context_level=int(self.controls.get("context_level", 0)),
                test_mode=str(self.controls.get("test_mode", "default")),
                timeout_s=self.timeout_s,
                num_ctx=self.num_ctx,
                preferred_model=self.preferred_model,
                preferred_url=self.preferred_url,
            )
            self.live_candidates = {}
            self.selected_candidate_id = None
            self.machine_state["task"] = task_text
            self.machine_state["stage"] = "queued"
            self.machine_state["stage_label"] = "queued"
            self.machine_state["status"] = "RUNNING"
            self.machine_state["branch_count"] = 0
            self.machine_state["last_event"] = "queued"
            self.machine_state["context_level"] = request.context_level
            self.machine_state["test_mode"] = request.test_mode
            self.session.task_text = task_text
            self.session.files_text = " ".join(files)
            self.session.resume_request = _request_payload(request)
            self._persist_session()
        threading.Thread(target=self._run_worker, args=(request,), daemon=True).start()
        return {"ok": True}

    def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle one command-palette style instruction."""

        with self._lock:
            self.session.task_text = str(payload.get("task", self.session.task_text))
            self.session.files_text = str(payload.get("files", self.session.files_text))
        command = str(payload.get("command", "")).strip()
        if not command:
            return {"ok": False, "error": "missing command"}
        raw = command.lstrip(":").strip()
        parts = raw.split()
        if not parts:
            return {"ok": False, "error": "missing command"}
        cmd = parts[0].lower()
        args = [part.lower() for part in parts[1:]]
        if cmd == "run":
            return self.start_run(payload, auto=True)
        if cmd == "step":
            return self.start_run(payload, auto=False)
        if cmd == "resume":
            return self.resume_last_request()
        if cmd == "stop":
            return self.handle_action({"action": "stop"})
        if cmd == "accept":
            return self.accept_selected_patch()
        if cmd == "reject":
            return self.reject_selection()
        if cmd == "revert":
            if args and args[0] == "apply":
                return self.apply_safe_revert()
            return self.preview_safe_revert()
        if cmd == "mode" and args:
            return self.set_mode_override(args[0])
        if cmd == "plan" and args:
            with self._lock:
                self.controls["planner"] = args[0] == "on"
                self._log(f"Planner {'on' if self.controls['planner'] else 'off'}")
            return {"ok": True}
        if cmd == "tau" and args:
            return self.set_tau(args[0])
        if cmd == "redteam" and args:
            with self._lock:
                self.controls["redteam"] = args[0] == "on"
                self._log(
                    f"Model redteam {'on' if self.controls['redteam'] else 'off'}"
                )
            return {"ok": True}
        if cmd == "tests" and args:
            return self.set_test_mode(args[0])
        if cmd in {"expand", "shrink"}:
            return self.adjust_context(1 if cmd == "expand" else -1)
        if cmd == "export":
            return self.export_state()
        if cmd == "debug" and args:
            with self._lock:
                self.controls["debug"] = args[0] == "on"
                self._log(f"Debug {'on' if self.controls['debug'] else 'off'}")
            return {"ok": True}
        if cmd == "quit":
            return self.handle_action({"action": "shutdown"})
        self._log(f"Unknown command: {raw}")
        return {"ok": False, "error": "unknown command"}

    def set_mode_override(self, value: str) -> dict[str, Any]:
        """Update the active search mode."""

        mapping = {
            "auto": "AUTO",
            "simple": "SIMPLE",
            "bi": "BISECT",
            "bisect": "BISECT",
            "tri": "TRISECT",
            "trisect": "TRISECT",
        }
        if value not in mapping:
            self._log("Mode must be auto, simple, bi, or tri.")
            return {"ok": False, "error": "invalid mode"}
        with self._lock:
            self.controls["mode_override"] = mapping[value]
            self.machine_state["mode_override"] = mapping[value]
            self.machine_state["mode"] = mapping[value]
            self._log(f"Mode override: {mapping[value]}")
            self._persist_session()
        return {"ok": True}

    def set_tau(self, value: str) -> dict[str, Any]:
        """Update the risk threshold."""

        try:
            parsed = max(0.0, min(1.0, float(value)))
        except ValueError:
            self._log("Tau must be a number between 0 and 1.")
            return {"ok": False, "error": "invalid tau"}
        with self._lock:
            self.controls["risk_threshold"] = parsed
            self.machine_state["risk_threshold"] = parsed
            self._log(f"Risk threshold set to {parsed:.2f}")
            self._persist_session()
        return {"ok": True}

    def select_candidate(self, candidate_id: str) -> None:
        """Select one live candidate."""

        with self._lock:
            if candidate_id in self.live_candidates:
                self.selected_candidate_id = candidate_id
                self.selected_record = None
                self.session.selected_candidate_id = candidate_id
                self.session.selected_record_id = None
                self._persist_session()

    def select_history(self, record_id: str) -> None:
        """Select one historical result."""

        with self._lock:
            for record in self.history:
                if record.identifier == record_id:
                    self.selected_candidate_id = None
                    self.selected_record = record
                    self.session.selected_candidate_id = None
                    self.session.selected_record_id = record.identifier
                    self._persist_session()
                    return

    def accept_selected_patch(self) -> dict[str, Any]:
        """Apply the selected candidate or persisted patch."""

        with self._lock:
            if (
                self.selected_candidate_id is not None
                and self.selected_candidate_id in self.live_candidates
            ):
                candidate = self.live_candidates[self.selected_candidate_id]
                patch = candidate.patch
                label = f"live candidate {candidate.identifier}"
            elif (
                self.selected_record is not None
                and self.selected_record.patch_path is not None
            ):
                if bool(self.selected_record.payload.get("applied")):
                    self._log("That patch was already applied.")
                    return {"ok": False, "error": "already applied"}
                patch = self.selected_record.diff_text
                label = f"patch {self.selected_record.patch_path}"
            else:
                self._log("No accepted patch is selected.")
                return {"ok": False, "error": "missing selection"}
        try:
            apply_unified_diff(self.repo_root, patch)
        except ValueError as exc:
            self._log(f"Could not apply patch: {exc}")
            return {"ok": False, "error": PATCH_APPLY_ERROR}
        self._remember_applied_patch(
            label=label,
            patch=patch,
            files_touched=extract_changed_files(patch),
            source="browser_accept",
            task=str(self.machine_state.get("task", "")),
            identifier=self.selected_candidate_id
            or (
                self.selected_record.identifier
                if self.selected_record is not None
                else ""
            ),
            patch_path=str(self.selected_record.patch_path)
            if self.selected_record is not None
            and self.selected_record.patch_path is not None
            else None,
        )
        self._log(f"Applied {label}")
        return {"ok": True}

    def reject_selection(self) -> dict[str, Any]:
        """Reject the selected live candidate or clear the current selection."""

        with self._lock:
            if (
                self.selected_candidate_id is not None
                and self.selected_candidate_id in self.live_candidates
            ):
                rejected = self.selected_candidate_id
                del self.live_candidates[rejected]
                self.selected_candidate_id = next(iter(self.live_candidates), None)
                self._log(f"Rejected live candidate {rejected}.")
                self._persist_session()
                return {"ok": True}
            self.selected_record = None
            self._log("Reject cleared the current selection.")
            self._persist_session()
            return {"ok": True}

    def export_state(self) -> dict[str, Any]:
        """Write the current browser snapshot to disk."""

        export_path = self.repo_root / ".forge" / "ui-export.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._session_snapshot()
        export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._log(f"Exported UI state to {export_path}")
        return {"ok": True, "path": str(export_path)}

    def resume_last_request(self) -> dict[str, Any]:
        """Resume the last remembered task request."""

        with self._lock:
            request = dict(self.session.resume_request or {})
        if not request:
            self._log("No paused task is ready to resume yet.")
            return {"ok": False, "error": "missing resume request"}
        payload = {
            "task": str(request.get("task_text", "")),
            "files": " ".join(request.get("files", [])),
            "controls": {
                **dict(self.controls),
                "mode_override": str(
                    request.get(
                        "mode_override", self.controls.get("mode_override", "AUTO")
                    )
                ),
                "risk_threshold": float(
                    request.get(
                        "risk_threshold", self.controls.get("risk_threshold", 0.35)
                    )
                ),
                "context_level": int(
                    request.get("context_level", self.controls.get("context_level", 0))
                ),
                "test_mode": str(
                    request.get("test_mode", self.controls.get("test_mode", "default"))
                ),
            },
        }
        return self.start_run(payload, auto=bool(request.get("auto_loop", False)))

    def adjust_context(self, delta: int) -> dict[str, Any]:
        """Adjust the context breadth used for future runs."""

        with self._lock:
            current = int(self.controls.get("context_level", 0))
            updated = max(0, min(3, current + delta))
            if updated == current:
                self._log(f"Context already at level {current}.")
                return {"ok": False, "error": "context unchanged"}
            self.controls["context_level"] = updated
            self.machine_state["context_level"] = updated
            self._persist_session()
            self._log(
                f"Context level {updated}: up to {6 + updated * 2} files, excerpt budget {1200 + updated * 800} chars."
            )
        return {"ok": True}

    def set_test_mode(self, value: str) -> dict[str, Any]:
        """Update the active test mode."""

        if value not in {"default", "fast", "full"}:
            self._log("Test mode must be default, fast, or full.")
            return {"ok": False, "error": "invalid test mode"}
        with self._lock:
            self.controls["test_mode"] = value
            self.machine_state["test_mode"] = value
            self._persist_session()
            if value == "fast":
                self._log(
                    "Test mode fast: Forge will target explicit test files when possible."
                )
            else:
                self._log(f"Test mode {value} enabled.")
        return {"ok": True}

    def preview_safe_revert(self) -> dict[str, Any]:
        """Preview the most recent safe revert action."""

        with self._lock:
            if not self.applied_history:
                self._log("Nothing in Forge lineage is ready to revert.")
                return {"ok": False, "error": "nothing to revert"}
            latest = self.applied_history[-1]
            touched = ", ".join(latest.files_touched[:4]) or "unknown files"
            self._log(
                f"Ready to revert {latest.label} touching {touched}. "
                "Run `revert apply` to undo it."
            )
        return {"ok": True}

    def apply_safe_revert(self) -> dict[str, Any]:
        """Undo the most recent applied Forge delta."""

        with self._lock:
            if not self.applied_history:
                self._log("Nothing in Forge lineage is ready to revert.")
                return {"ok": False, "error": "nothing to revert"}
            latest = self.applied_history[-1]
        try:
            apply_unified_diff(self.repo_root, latest.revert_patch)
        except ValueError as exc:
            self._log(f"Could not revert {latest.label}: {exc}")
            return {"ok": False, "error": PATCH_REVERT_ERROR}
        with self._lock:
            self.applied_history.pop()
            self.machine_state["status"] = "WAITING"
            self.machine_state["stage_label"] = "reverted"
            self.machine_state["last_event"] = f"reverted {latest.identifier}"
            self._persist_session()
        self._log(f"Reverted {latest.label}")
        return {"ok": True}

    def _remember_applied_patch(
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
            identifier=identifier or _task_identifier(label),
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
        self.applied_history = self.applied_history[-24:]
        self._persist_session()

    def _session_snapshot(self) -> dict[str, Any]:
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
                candidate_id: _candidate_payload(candidate)
                for candidate_id, candidate in self.live_candidates.items()
            },
            "logs": list(self.logs),
            "applied_history": [item.as_dict() for item in self.applied_history],
            "resume_request": self.session.resume_request,
        }

    def _persist_session(self) -> None:
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
            candidate_id: _candidate_payload(candidate)
            for candidate_id, candidate in self.live_candidates.items()
        }
        self.session.logs = list(self.logs)
        self.session.applied_history = list(self.applied_history)
        save_session(self.session_path, self.session)

    def shutdown_server(self) -> None:
        """Stop the backing HTTP server."""

        if self.server is not None:
            time.sleep(0.15)
            self.server.shutdown()

    def _run_worker(self, request: RunRequest) -> None:
        attempts = 0
        max_attempts = 4 if request.auto_loop else 1
        with self._lock:
            self.stop_requested = False
            self._set_running_state(True)
        while attempts < max_attempts:
            with self._lock:
                if self.stop_requested:
                    break
            attempts += 1
            with self._lock:
                self._set_stage("RUNNING", f"iter {attempts}")
            client, runtime_summary = _build_client_from_request(request)
            with self._lock:
                self.runtime_summary = runtime_summary
            if client is None:
                with self._lock:
                    self._set_stage("RUNTIME MISSING", "runtime unavailable")
                    self._log(_runtime_doctor_message(runtime_summary))
                break
            orchestrator = ForgeOrchestrator(
                request.repo_root,
                apply_accepted=request.apply_accepted,
                client=client,
            )
            task = ForgeTask(
                identifier=_task_identifier(request.task_text),
                summary=request.task_text,
                scope="S1",
                todo="T1",
                target_files=request.files,
                context_level=request.context_level,
                test_mode=request.test_mode,
            )
            try:
                result = orchestrator.process(
                    task,
                    dry_run=False,
                    mode_override=None
                    if request.mode_override == "AUTO"
                    else request.mode_override,
                    risk_threshold=request.risk_threshold,
                    event_sink=self.handle_event,
                )
            except Exception as exc:  # pragma: no cover - interactive safety net
                with self._lock:
                    self._set_stage("BLOCKED", str(exc))
                    self._log(f"Run failed: {exc}")
                break
            self.record_result(result)
            if not request.auto_loop or result["status"] in {
                "promote",
                "manual_review",
            }:
                break
        with self._lock:
            self._set_running_state(False)
            if self.stop_requested:
                self._set_stage("INTERRUPTED", "interrupted")
                self._log("Forge stopped by operator.")

    def handle_event(self, event: dict[str, Any]) -> None:
        """Apply one streaming Forge event."""

        stage = str(event.get("stage", "event"))
        with self._lock:
            self.machine_state["last_event"] = str(event.get("message", stage))
            self.machine_state["stage"] = stage
            self.machine_state["stage_label"] = _stage_label(stage)
            self.machine_state["status"] = _event_status(
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
                int(self.machine_state.get("branch_count", 0)),
                len(self.live_candidates),
            )
            self._log(f"[{stage}] {event.get('message', '')}")
            self._persist_session()

    def record_result(self, result: dict[str, Any]) -> None:
        """Ingest the final Forge result payload."""

        record = history_record_from_result(result)
        with self._lock:
            self.selected_record = record
            self.session.selected_record_id = record.identifier
            self.machine_state["status"] = _status_from_result(result)
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
                    "test_mode", self.machine_state.get("test_mode", "default")
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
            if bool(result.get("applied")) and record.diff_text.startswith(
                "diff --git "
            ):
                self._remember_applied_patch(
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
            self._log(f"{result['status']}: {result['detail']}")
            self._persist_session()

    def _apply_controls(self, controls: dict[str, Any], *, auto: bool) -> None:
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
            controls.get("mode_override", self.controls["mode_override"] or "AUTO")
        ).upper()
        self.controls["risk_threshold"] = float(
            controls.get("risk_threshold", self.controls["risk_threshold"])
        )
        self.controls["context_level"] = int(
            controls.get("context_level", self.controls.get("context_level", 0))
        )
        self.controls["test_mode"] = str(
            controls.get("test_mode", self.controls.get("test_mode", "default"))
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

    def _current_record(self) -> HistoryRecord | CandidateRecord | None:
        if self.selected_candidate_id is not None:
            candidate = self.live_candidates.get(self.selected_candidate_id)
            if candidate is not None:
                return candidate
        return self.selected_record

    def _set_running_state(self, running: bool) -> None:
        self.running = running
        if running:
            self.machine_state["status"] = "RUNNING"
            self.machine_state["stage_label"] = "running"
        elif self.machine_state.get("status") == "RUNNING":
            self.machine_state["status"] = "WAITING"
            if self.machine_state.get("stage") in {"queued", "idle"}:
                self.machine_state["stage_label"] = "idle"
        self._persist_session()

    def _set_stage(self, status: str, label: str) -> None:
        self.machine_state["status"] = status
        self.machine_state["stage_label"] = label
        self.machine_state["last_event"] = label
        self._persist_session()

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
            status=_candidate_status(stage, candidate.status),
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

    def _log(self, message: str) -> None:
        self.logs.append(message)
        self._persist_session()


def quickstart_steps() -> list[str]:
    """Return the visible browser-app quickstart."""

    return list(DEFAULT_UI_STATE_CONFIG.quickstart)


def runtime_doctor_steps(runtime_summary: str) -> list[str]:
    """Return low-friction runtime help for the browser app."""

    if "not detected" in runtime_summary.lower():
        return [
            "Open the Ollama app and wait a few seconds.",
            "Click Check Tools.",
            "If it still fails, restart Ollama and try again.",
        ]
    return list(DEFAULT_UI_STATE_CONFIG.runtime_help_ready)


def launch(
    repo_root: Path,
    *,
    preferred_model: str | None = None,
    preferred_url: str | None = None,
    timeout_s: int = 300,
    num_ctx: int = 2048,
    host: str = "127.0.0.1",
    port: int = DEFAULT_BROWSER_PORT,
    open_browser: bool = True,
) -> int:
    """Launch the Forge browser app."""

    state = BrowserState(
        repo_root,
        preferred_model=preferred_model,
        preferred_url=preferred_url,
        timeout_s=timeout_s,
        num_ctx=num_ctx,
    )
    server = ThreadingHTTPServer((host, port), _handler_for(state))
    server.daemon_threads = True
    state.attach_server(server)
    url = f"http://{host}:{server.server_port}/"
    print(f"Forge browser app: {url}")
    print(
        "Press Ctrl+C in this process or use the Shutdown button in the browser to stop Forge."
    )
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - depends on host browser setup
            print(f"Open this URL manually if your browser did not open: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _handler_for(state: BrowserState) -> type[BaseHTTPRequestHandler]:
    class ForgeBrowserHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                self._html_response(_browser_page())
                return
            if self.path == "/api/state":
                self._json_response(state.snapshot())
                return
            self.send_error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/action":
                self.send_error(404, "not found")
                return
            payload = self._read_json()
            result = state.handle_action(payload)
            self._json_response(result)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))

        def _json_response(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html_response(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ForgeBrowserHandler


def _candidate_status(stage: str, current: str) -> str:
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


def _split_files(raw: str) -> list[str]:
    return [item for item in raw.replace(",", " ").split() if item]


def _runtime_block_message() -> str:
    return (
        "Forge could not find a ready Ollama runtime. "
        "Run `./forge --check`, then start Ollama or pull a coder model if needed."
    )


def _browser_page() -> str:
    page = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forge</title>
  <style>
    :root {
      --bg: #000000;
      --panel: #050505;
      --panel-alt: #0b0b0b;
      --panel-soft: #101010;
      --line: #202020;
      --line-strong: #333333;
      --text: #f5f7f7;
      --muted: #9aa3a6;
      --soft: #cdd4d6;
      --accent: #00d5ff;
      --accent-soft: rgba(0, 213, 255, 0.12);
      --good: #2dff91;
      --warn: #ffcd4a;
      --bad: #ff5a4e;
      --shadow: 0 20px 70px rgba(0, 0, 0, 0.78);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Inter", system-ui, sans-serif;
      background:
        radial-gradient(circle at 25% 0%, rgba(0, 213, 255, 0.08), transparent 28%),
        linear-gradient(180deg, #000000 0%, #020202 100%);
      color: var(--text);
      min-height: 100vh;
      padding: 24px 24px 260px;
    }
    .topbar, .status-strip, .card {
      background: rgba(5, 5, 5, 0.96);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 22px 24px;
      margin-bottom: 16px;
    }
    .topbar h1 {
      margin: 0;
      font-size: 28px;
      letter-spacing: 0.02em;
    }
    .topbar p {
      margin: 6px 0 0;
      color: var(--muted);
    }
    .pill {
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-weight: 700;
      background: var(--panel-alt);
      color: var(--soft);
    }
    .pill.running, .pill.planning, .pill.testing, .pill.attacking {
      color: var(--accent);
      border-color: rgba(0, 213, 255, 0.42);
      background: var(--accent-soft);
    }
    .pill.ready, .pill.waiting {
      color: var(--good);
      border-color: rgba(45, 255, 145, 0.34);
      background: rgba(45, 255, 145, 0.08);
    }
    .pill.blocked, .pill.runtime {
      color: var(--bad);
      border-color: rgba(255, 90, 78, 0.42);
      background: rgba(255, 90, 78, 0.10);
    }
    .status-strip {
      padding: 16px 18px;
      margin-bottom: 16px;
      white-space: pre-wrap;
      line-height: 1.45;
      color: var(--muted);
    }
    .runtime-banner {
      display: grid;
      gap: 8px;
      padding: 14px 18px;
      margin-bottom: 16px;
      border: 1px solid rgba(0, 213, 255, 0.26);
      border-radius: 18px;
      background: rgba(0, 213, 255, 0.07);
      color: var(--soft);
      box-shadow: var(--shadow);
    }
    .runtime-banner.bad {
      border-color: rgba(255, 90, 78, 0.42);
      background: rgba(255, 90, 78, 0.10);
    }
    .runtime-banner.good {
      border-color: rgba(45, 255, 145, 0.28);
      background: rgba(45, 255, 145, 0.07);
    }
    .runtime-banner strong {
      color: var(--text);
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(260px, 320px) 1fr;
      gap: 16px;
    }
    .sidebar, .main {
      display: grid;
      gap: 16px;
      align-content: start;
    }
    .card {
      padding: 18px;
    }
    .card h2 {
      margin: 0 0 12px;
      font-size: 13px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .card.hidden, .hidden {
      display: none;
    }
    .section-note {
      margin: -4px 0 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .summary {
      white-space: pre-wrap;
      line-height: 1.45;
      color: var(--text);
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      margin: 0;
    }
    .list {
      display: grid;
      gap: 8px;
      max-height: 220px;
      overflow: auto;
    }
    .list button {
      width: 100%;
      text-align: left;
      background: var(--panel-alt);
      color: var(--text);
      border: 1px solid transparent;
      border-radius: 14px;
      padding: 12px 13px;
      cursor: pointer;
    }
    .list button.selected { border-color: var(--accent); }
    .list button:hover { border-color: var(--line-strong); }
    .list .empty {
      color: var(--muted);
      padding: 8px 2px;
    }
    .workspace {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .pane.wide {
      grid-column: 1 / -1;
    }
    .pane pre {
      margin: 0;
      white-space: pre-wrap;
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      line-height: 1.45;
      color: #e6eef3;
      max-height: 360px;
      overflow: auto;
    }
    .legend, .quickstart {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.5;
    }
    .legend strong {
      color: var(--text);
      display: inline-block;
      min-width: 104px;
    }
    .helper-shell {
      display: grid;
      gap: 14px;
    }
    .task-examples, .preset-grid {
      display: grid;
      gap: 8px;
    }
    .task-examples {
      grid-template-columns: 1fr;
    }
    .composer .preset-grid {
      flex: 1 1 520px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .chip, .preset {
      width: 100%;
      text-align: left;
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-alt);
      cursor: pointer;
    }
    .chip {
      padding: 10px 12px;
    }
    .preset {
      padding: 12px 13px;
    }
    .chip:hover, .preset:hover {
      border-color: var(--line-strong);
      background: var(--panel-soft);
    }
    .preset.active {
      border-color: rgba(0, 213, 255, 0.58);
      background: var(--accent-soft);
    }
    .preset strong {
      display: block;
      margin-bottom: 4px;
    }
    .preset span {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
    #capabilities-view {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .helper-title {
      margin: 0 0 8px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .helper-details {
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .helper-details summary {
      cursor: pointer;
      color: var(--text);
      font-weight: 600;
      margin-bottom: 8px;
    }
    .composer {
      position: fixed;
      left: 24px;
      right: 24px;
      bottom: 20px;
      background: rgba(0, 0, 0, 0.98);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 25px 55px rgba(0, 0, 0, 0.35);
      padding: 16px;
      backdrop-filter: blur(18px);
    }
    .composer textarea, .composer input, .composer select {
      width: 100%;
      border: 1px solid var(--line-strong);
      background: #050505;
      color: var(--text);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
    }
    .composer textarea {
      min-height: 88px;
      resize: vertical;
      margin-bottom: 10px;
    }
    .controls, .actions, .command-row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .advanced {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .advanced summary {
      cursor: pointer;
      color: var(--muted);
      font-weight: 600;
      list-style: none;
    }
    .advanced summary::-webkit-details-marker {
      display: none;
    }
    .controls label, .small {
      color: var(--muted);
      font-size: 13px;
    }
    .check {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border-radius: 999px;
      background: var(--panel-alt);
      border: 1px solid var(--line);
    }
    .button {
      border: 1px solid var(--line-strong);
      background: var(--panel-soft);
      color: var(--text);
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 700;
      cursor: pointer;
    }
    .button.primary { background: #003241; border-color: #00b8df; }
    .button.warn { border-color: rgba(255, 205, 74, 0.52); background: rgba(255, 205, 74, 0.10); }
    .button.bad { border-color: rgba(255, 90, 78, 0.46); background: rgba(255, 90, 78, 0.10); }
    .button:disabled {
      cursor: not-allowed;
      opacity: 0.46;
      filter: grayscale(0.4);
    }
    .button:hover { filter: brightness(1.08); }
    @media (max-width: 1100px) {
      .layout { grid-template-columns: 1fr; }
      .workspace { grid-template-columns: 1fr; }
      .composer .preset-grid, #capabilities-view { grid-template-columns: 1fr; }
      body { padding-bottom: 360px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div>
      <h1>Forge</h1>
      <p>Type the change you want. Forge writes, checks, and shows you the result before anything is used.</p>
    </div>
    <div id="status-pill" class="pill">WAITING</div>
  </header>

  <section id="status-strip" class="status-strip">Loading Forge…</section>
  <section id="runtime-banner" class="runtime-banner hidden"></section>

  <div class="layout">
    <aside class="sidebar">
      <section class="card">
        <h2>Start Here</h2>
        <div class="helper-shell">
          <div>
            <div class="helper-title">What to do</div>
            <ol id="quickstart" class="quickstart"></ol>
          </div>
          <div>
            <div class="helper-title">Example tasks</div>
            <div id="example-tasks" class="task-examples"></div>
          </div>
          <div>
            <div class="helper-title">AI setup</div>
            <ol id="doctor" class="quickstart"></ol>
          </div>
          <details class="helper-details">
            <summary>Help and shortcuts</summary>
            <ul id="legend" class="legend"></ul>
          </details>
        </div>
      </section>
      <section id="candidate-card" class="card hidden">
        <h2>Choices to Review</h2>
        <p class="section-note">Forge may compare more than one safe-looking option. Pick one to inspect.</p>
        <div id="candidate-list" class="list"></div>
      </section>
      <section id="history-card" class="card hidden">
        <h2>Recent Work</h2>
        <p class="section-note">Open a previous result to inspect or reuse it.</p>
        <div id="history-list" class="list"></div>
      </section>
    </aside>

    <section class="main">
      <section class="card">
        <h2>What Forge Is Doing</h2>
        <pre id="control-summary" class="summary">Loading…</pre>
      </section>
      <section class="workspace">
        <section class="card pane wide">
          <h2>Proposed Change</h2>
          <p class="section-note">This is the exact code change Forge wants to make.</p>
          <pre id="diff-view">No diffs yet.</pre>
        </section>
        <section class="card pane">
          <h2>Checks</h2>
          <p class="section-note">Forge runs tests and safety checks before a change is trusted.</p>
          <pre id="tests-view">No result selected yet.</pre>
        </section>
        <section class="card pane">
          <h2>Safety Review</h2>
          <p class="section-note">Forge tries to break its own change before you use it.</p>
          <pre id="redteam-view">No result selected yet.</pre>
        </section>
        <section class="card pane">
          <h2>Activity Log</h2>
          <p class="section-note">Plain trail of what happened, newest at the bottom.</p>
          <pre id="logs-view">Starting Forge…</pre>
        </section>
        <section class="card pane wide">
          <h2>Files Involved</h2>
          <p class="section-note">The files Forge believes are relevant to the selected result.</p>
          <pre id="files-view">Nothing selected yet.</pre>
        </section>
        <section class="card pane wide">
          <h2>Connected Tools</h2>
          <p class="section-note">Local tools Forge can see right now. Nothing here runs silently.</p>
          <div id="capabilities-view" class="preset-grid"></div>
        </section>
      </section>
    </section>
  </div>

  <section class="composer">
    <textarea id="task-input" placeholder="What would you like Forge to change? Example: Make the login error easier to understand without changing how sign-in works."></textarea>
    <input id="files-input" placeholder="Optional: files to focus on, separated by spaces">
    <input id="tool-profile-input" type="hidden" value="codex">
    <div class="controls">
      <span class="small">Tool style</span>
      <div id="tool-profiles" class="preset-grid"></div>
    </div>
    <div class="controls">
      <span class="small">Workflow</span>
      <div id="workflow-presets" class="preset-grid"></div>
    </div>
    <div class="actions">
      <button class="button primary" id="run-button">Start</button>
      <button class="button" id="step-button">Try Once</button>
      <button class="button warn" id="stop-button">Stop</button>
      <button class="button" id="runtime-button">Check Tools</button>
      <button class="button" id="accept-button">Use This Change</button>
      <button class="button bad" id="reject-button">Skip This Change</button>
      <button class="button" id="export-button">Save Snapshot</button>
      <button class="button bad" id="shutdown-button">Close App</button>
    </div>
    <details class="advanced">
      <summary>Expert tools</summary>
      <div class="controls">
        <label class="check"><input type="checkbox" id="auto-input"> Auto loop</label>
        <label class="check"><input type="checkbox" id="apply-input" checked> Apply accepted result</label>
        <label class="check"><input type="checkbox" id="planner-input"> Planner</label>
        <label class="check"><input type="checkbox" id="redteam-input"> Model redteam</label>
        <label class="check"><input type="checkbox" id="debug-input"> Debug</label>
        <label class="small">Mode
          <select id="mode-input">
            <option value="AUTO">AUTO</option>
            <option value="SIMPLE">SIMPLE</option>
            <option value="BISECT">BISECT</option>
            <option value="TRISECT">TRISECT</option>
          </select>
        </label>
        <label class="small">Risk τ
          <input id="tau-input" type="number" min="0" max="1" step="0.05" value="0.35">
        </label>
        <label class="small">Context
          <select id="context-input">
            <option value="0">L0</option>
            <option value="1">L1</option>
            <option value="2">L2</option>
            <option value="3">L3</option>
          </select>
        </label>
        <label class="small">Tests
          <select id="tests-input">
            <option value="default">default</option>
            <option value="fast">fast</option>
            <option value="full">full</option>
          </select>
        </label>
        <span class="small">Ctrl+Enter starts a run. The command bar below is optional.</span>
      </div>
      <div class="command-row">
        <input id="command-input" placeholder="Optional command bar: resume | mode tri | tests fast | revert apply">
        <button class="button" id="command-button">Run Command</button>
      </div>
    </details>
  </section>

  <script>
    const stateUrl = "/api/state";
    const actionUrl = "/api/action";
    const ids = {
      statusPill: document.getElementById("status-pill"),
      statusStrip: document.getElementById("status-strip"),
      runtimeBanner: document.getElementById("runtime-banner"),
      controlSummary: document.getElementById("control-summary"),
      diff: document.getElementById("diff-view"),
      tests: document.getElementById("tests-view"),
      redteam: document.getElementById("redteam-view"),
      files: document.getElementById("files-view"),
      logs: document.getElementById("logs-view"),
      capabilities: document.getElementById("capabilities-view"),
      candidateList: document.getElementById("candidate-list"),
      historyList: document.getElementById("history-list"),
      candidateCard: document.getElementById("candidate-card"),
      historyCard: document.getElementById("history-card"),
      quickstart: document.getElementById("quickstart"),
      doctor: document.getElementById("doctor"),
      legend: document.getElementById("legend"),
      examples: document.getElementById("example-tasks"),
      presets: document.getElementById("workflow-presets"),
      toolProfiles: document.getElementById("tool-profiles"),
      toolProfile: document.getElementById("tool-profile-input"),
      task: document.getElementById("task-input"),
      filesInput: document.getElementById("files-input"),
      auto: document.getElementById("auto-input"),
      apply: document.getElementById("apply-input"),
      planner: document.getElementById("planner-input"),
      redteamInput: document.getElementById("redteam-input"),
      debug: document.getElementById("debug-input"),
      mode: document.getElementById("mode-input"),
      tau: document.getElementById("tau-input"),
      context: document.getElementById("context-input"),
      testsMode: document.getElementById("tests-input"),
      command: document.getElementById("command-input")
    };

    async function post(payload) {
      await fetch(actionUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      await refresh();
    }

    function controlPayload() {
      return {
        auto: ids.auto.checked,
        apply: ids.apply.checked,
        planner: ids.planner.checked,
        redteam: ids.redteamInput.checked,
        debug: ids.debug.checked,
        mode_override: ids.mode.value,
        risk_threshold: Number(ids.tau.value || 0.35),
        context_level: Number(ids.context.value || 0),
        test_mode: ids.testsMode.value,
        tool_profile: ids.toolProfile.value || "codex"
      };
    }

    async function refresh() {
      const response = await fetch(stateUrl, {cache: "no-store"});
      const data = await response.json();
      render(data);
    }

    function render(data) {
      const status = data.control_summary.match(/^\[(.+?)\]/m);
      const statusText = status ? status[1] : "WAITING";
      ids.statusPill.textContent = statusText;
      ids.statusPill.className = `pill ${statusClass(statusText)}`;
      ids.statusStrip.textContent = data.status_strip;
      ids.controlSummary.textContent = data.control_summary;
      ids.diff.textContent = data.diff_text;
      ids.tests.textContent = data.tests_text;
      ids.redteam.textContent = data.redteam_text;
      ids.files.textContent = data.files_panel_text;
      ids.logs.textContent = data.logs.length ? data.logs.join("\n") : "Nothing has run yet.";
      ids.logs.scrollTop = ids.logs.scrollHeight;
      renderRuntimeBanner(data);
      if (!ids.task.matches(":focus")) {
        ids.task.value = data.task_text || ids.task.value;
      }
      if (!ids.filesInput.matches(":focus")) {
        ids.filesInput.value = data.files_text || ids.filesInput.value;
      }

      ids.auto.checked = Boolean(data.controls.auto);
      ids.apply.checked = Boolean(data.controls.apply);
      ids.planner.checked = Boolean(data.controls.planner);
      ids.redteamInput.checked = Boolean(data.controls.redteam);
      ids.debug.checked = Boolean(data.controls.debug);
      ids.mode.value = data.controls.mode_override || "AUTO";
      ids.tau.value = data.controls.risk_threshold;
      ids.context.value = String(data.controls.context_level || 0);
      ids.testsMode.value = data.controls.test_mode || "default";
      ids.toolProfile.value = data.controls.tool_profile || "codex";

      renderList(ids.quickstart, data.quickstart, item => `<li>${escapeHtml(item)}</li>`);
      renderList(ids.doctor, data.doctor, item => `<li>${escapeHtml(item)}</li>`);
      renderList(ids.legend, data.legend, item => `<li><strong>${escapeHtml(item.command)}</strong>${escapeHtml(item.meaning)}</li>`);
      renderTaskExamples(data.example_tasks || []);
      renderPresets(data.workflow_presets || [], data.controls);
      renderToolProfiles(data.tool_profiles || [], data.controls);
      renderCapabilities(data.capabilities || []);
      renderButtons(ids.candidateList, data.live_candidates, "select_candidate");
      renderButtons(ids.historyList, data.history, "select_history");
      ids.candidateCard.classList.toggle("hidden", !data.live_candidates.length);
      ids.historyCard.classList.toggle("hidden", !data.history.length);
      updateButtons(data);
    }

    function renderList(node, items, renderItem) {
      node.innerHTML = items.map(renderItem).join("");
    }

    function renderButtons(node, items, action) {
      if (!items.length) {
        node.innerHTML = "";
        return;
      }
      node.innerHTML = items.map(item => {
        const cls = item.selected ? "selected" : "";
        return `<button class="${cls}" data-action="${action}" data-id="${escapeAttr(item.id)}">${escapeHtml(item.label)}</button>`;
      }).join("");
      node.querySelectorAll("button").forEach(button => {
        button.addEventListener("click", () => post({action: button.dataset.action, id: button.dataset.id}));
      });
    }

    function renderRuntimeBanner(data) {
      const summary = data.runtime_summary || "";
      const ready = !summary.toLowerCase().includes("not detected") && !summary.toLowerCase().includes("models: none");
      const title = ready ? "AI is ready" : "AI needs attention";
      const steps = (data.doctor || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
      ids.runtimeBanner.className = `runtime-banner ${ready ? "good" : "bad"}`;
      ids.runtimeBanner.innerHTML = `<strong>${title}</strong><span>${escapeHtml(summary)}</span><ol class="quickstart">${steps}</ol>`;
    }

    function renderTaskExamples(items) {
      ids.examples.innerHTML = items.map(item => `<button class="chip" type="button">${escapeHtml(item)}</button>`).join("");
      ids.examples.querySelectorAll("button").forEach(button => {
        button.addEventListener("click", () => {
          ids.task.value = button.textContent;
          ids.task.focus();
        });
      });
    }

    function renderPresets(items, controls) {
      ids.presets.innerHTML = items.map(item => {
        const active = presetMatches(item, controls) ? "active" : "";
        return `<button class="preset ${active}" type="button" data-id="${escapeAttr(item.id)}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.description)}</span></button>`;
      }).join("");
      ids.presets.querySelectorAll("button").forEach(button => {
        const preset = items.find(item => item.id === button.dataset.id);
        button.addEventListener("click", () => applyPreset(preset));
      });
    }

    function renderToolProfiles(items, controls) {
      ids.toolProfiles.innerHTML = items.map(item => {
        const active = item.id === (controls.tool_profile || "codex") ? "active" : "";
        return `<button class="preset tool-profile ${active}" type="button" data-id="${escapeAttr(item.id)}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.description)}</span></button>`;
      }).join("");
      ids.toolProfiles.querySelectorAll("button").forEach(button => {
        const profile = items.find(item => item.id === button.dataset.id);
        button.addEventListener("click", () => applyToolProfile(profile));
      });
    }

    function renderCapabilities(items) {
      if (!items.length) {
        ids.capabilities.innerHTML = '<div class="empty">No tool check has completed yet.</div>';
        return;
      }
      ids.capabilities.innerHTML = items.map(item => {
        const state = item.status === "ready" || item.status === "configured" ? "active" : "";
        return `<div class="preset ${state}"><strong>${escapeHtml(item.name)}: ${escapeHtml(item.status)}</strong><span>${escapeHtml(item.detail)}</span></div>`;
      }).join("");
    }

    function applyPreset(preset) {
      if (!preset) return;
      ids.auto.checked = Boolean(preset.auto);
      ids.planner.checked = Boolean(preset.planner);
      ids.redteamInput.checked = true;
      ids.mode.value = preset.mode || "AUTO";
      ids.context.value = String(preset.context || 0);
      ids.testsMode.value = preset.tests || "default";
    }

    function applyToolProfile(profile) {
      if (!profile) return;
      ids.toolProfile.value = profile.id || "codex";
      ids.auto.checked = Boolean(profile.auto);
      ids.planner.checked = Boolean(profile.planner);
      ids.redteamInput.checked = Boolean(profile.redteam);
      ids.mode.value = profile.mode || "AUTO";
      ids.context.value = String(profile.context || 0);
      ids.testsMode.value = profile.tests || "default";
      ids.toolProfiles.querySelectorAll("button").forEach(button => {
        button.classList.toggle("active", button.dataset.id === profile.id);
      });
      post({action: "set_tool_profile", id: profile.id});
    }

    function presetMatches(preset, controls) {
      return preset.mode === controls.mode_override
        && Number(preset.context) === Number(controls.context_level || 0)
        && preset.tests === controls.test_mode;
    }

    function updateButtons(data) {
      const hasSelection = data.selected_label && !data.selected_label.toLowerCase().includes("nothing");
      document.getElementById("stop-button").disabled = !data.running;
      document.getElementById("accept-button").disabled = !hasSelection;
      document.getElementById("reject-button").disabled = !hasSelection;
    }

    function statusClass(status) {
      const lower = status.toLowerCase();
      if (lower.includes("runtime")) return "runtime";
      if (lower.includes("blocked") || lower.includes("interrupted")) return "blocked";
      if (lower.includes("ready") || lower.includes("commit")) return "ready";
      if (lower.includes("planning")) return "planning";
      if (lower.includes("testing")) return "testing";
      if (lower.includes("attacking")) return "attacking";
      if (lower.includes("running")) return "running";
      return "waiting";
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[char]);
    }

    function escapeAttr(value) {
      return escapeHtml(value);
    }

    document.getElementById("run-button").addEventListener("click", () => post({action: "run", task: ids.task.value, files: ids.filesInput.value, controls: controlPayload()}));
    document.getElementById("step-button").addEventListener("click", () => post({action: "step", task: ids.task.value, files: ids.filesInput.value, controls: controlPayload()}));
    document.getElementById("stop-button").addEventListener("click", () => post({action: "stop"}));
    document.getElementById("runtime-button").addEventListener("click", () => post({action: "check_runtime"}));
    document.getElementById("accept-button").addEventListener("click", () => post({action: "accept"}));
    document.getElementById("reject-button").addEventListener("click", () => post({action: "reject"}));
    document.getElementById("export-button").addEventListener("click", () => post({action: "export"}));
    document.getElementById("shutdown-button").addEventListener("click", () => post({action: "shutdown"}));
    document.getElementById("command-button").addEventListener("click", () => {
      post({action: "command", command: ids.command.value, task: ids.task.value, files: ids.filesInput.value, controls: controlPayload()});
      ids.command.value = "";
    });

    ids.command.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        document.getElementById("command-button").click();
      }
    });

    ids.task.addEventListener("keydown", event => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        document.getElementById("run-button").click();
      }
    });

    refresh();
    setInterval(refresh, 900);
    ids.task.focus();
  </script>
</body>
</html>"""
    return page.replace(
        'value="0.35"', f'value="{DEFAULT_UI_STATE_CONFIG.risk_threshold:.2f}"', 1
    ).replace(
        "Number(ids.tau.value || 0.35)",
        f"Number(ids.tau.value || {DEFAULT_UI_STATE_CONFIG.risk_threshold:.2f})",
        1,
    )
