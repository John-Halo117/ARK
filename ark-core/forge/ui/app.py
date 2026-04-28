"""Textual control panel for Forge."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from ..core.orchestrator import ForgeOrchestrator
from ..exec.git import delta_id
from ..runtime.bootstrap import (
    RuntimeStatus,
    detect_runtime_status,
    ensure_runtime_ready,
)
from ..runtime.config import DEFAULT_UI_STATE_CONFIG
from ..transform.apply import apply_unified_diff, reverse_unified_diff
from ..types import ForgeTask
from .common import (
    CandidateRecord,
    HistoryRecord,
    RunRequest,
    artifacts_dir_for_repo,
    build_client_from_request,
    candidate_from_payload,
    candidate_payload,
    candidate_status,
    command_legend,
    event_status,
    example_tasks,
    find_candidate_index,
    find_history_index,
    history_record_from_result,
    load_history_records,
    parse_command as _parse_command,
    record_diff_text,
    render_candidate_summary,
    render_command_legend,
    render_control_panel,
    render_files_panel,
    render_redteam_panel,
    render_status_strip,
    render_test_panel,
    request_payload,
    runtime_doctor_message,
    selected_label,
    split_files,
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

__all__ = [
    "CandidateRecord",
    "HistoryRecord",
    "RunRequest",
    "artifacts_dir_for_repo",
    "command_legend",
    "example_tasks",
    "history_record_from_result",
    "load_history_records",
    "render_candidate_summary",
    "render_command_legend",
    "render_control_panel",
    "render_files_panel",
    "render_redteam_panel",
    "render_status_strip",
    "render_test_panel",
    "tool_profiles",
    "workflow_presets",
    "launch",
]


def launch(
    repo_root: Path,
    *,
    preferred_model: str | None = None,
    preferred_url: str | None = None,
    timeout_s: int = 300,
    num_ctx: int = 2048,
) -> int:
    """Launch the Forge operator UI."""

    try:
        from textual import on, work
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import (
            Button,
            Checkbox,
            Footer,
            Header,
            Input,
            Log,
            OptionList,
            Static,
            TextArea,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Forge TUI requires the `textual` package in ark-core/.venv. "
            "Install it with `cd ark-core && .venv/bin/pip install textual`."
        ) from exc

    class ForgeApp(App[None]):
        TITLE = "Forge"
        SUB_TITLE = "Deterministic self-coding control panel"
        CSS = """
        Screen {
            background: #0d1318;
            color: #edf3f7;
        }
        #root {
            height: 1fr;
            layout: vertical;
        }
        #status-strip {
            height: auto;
            margin-bottom: 1;
            border: round #3b6178;
            background: #111b23;
            padding: 0 1;
        }
        #task-bar, #control-bar, #row-top, #row-mid {
            height: auto;
            layout: horizontal;
        }
        #task-input {
            width: 1fr;
            margin-right: 1;
        }
        #files-input {
            width: 42;
        }
        #control-bar {
            margin: 1 0;
            height: auto;
        }
        #control-bar Button {
            margin-right: 1;
        }
        #row-top, #row-mid {
            height: 1fr;
            margin-bottom: 1;
        }
        #control-pane, #diff-pane, #redteam-pane, #tests-pane, #logs-pane {
            border: round #406074;
            background: #14202a;
            padding: 1;
        }
        #control-pane, #redteam-pane {
            width: 42;
            margin-right: 1;
        }
        #diff-pane, #tests-pane {
            width: 1fr;
        }
        #candidate-list {
            height: 8;
            margin: 1 0;
        }
        #history-list {
            height: 7;
            margin: 1 0;
        }
        #legend-view {
            margin-top: 1;
        }
        #diff-view {
            height: 1fr;
            border: round #335a6e;
        }
        #logs-pane {
            height: 12;
        }
        #log-view {
            height: 1fr;
        }
        #command-input {
            margin-top: 1;
            display: none;
        }
        .section {
            color: #7fc3ff;
            text-style: bold;
            margin-bottom: 1;
        }
        .hint {
            color: #89b7d5;
        }
        """
        BINDINGS = [
            ("enter", "step_run", "Step"),
            ("space", "toggle_auto_loop", "Auto"),
            ("p", "toggle_planner", "Planner"),
            ("m", "cycle_mode", "Mode"),
            ("d", "next_diff", "Diff"),
            ("t", "toggle_tests", "Tests"),
            ("r", "toggle_redteam_details", "Redteam"),
            ("b", "show_ban_hits", "Ban"),
            ("c", "expand_context_hint", "Context"),
            ("l", "safe_revert", "Revert"),
            (":", "open_palette", "Palette"),
            ("ctrl+p", "open_palette", "Palette"),
            ("ctrl+q", "quit", "Quit"),
            ("q", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
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
            self.running = False
            self.stop_requested = False
            self.redteam_expanded = False
            self.tests_expanded = False
            self.machine_state: dict[str, Any] = dict(default_machine_state())
            self.machine_state.update(self.session.machine_state)
            self.runtime_summary = self.session.runtime_summary
            self.runtime_status = detect_runtime_status(
                preferred_url=preferred_url,
                preferred_model=preferred_model,
            )
            self.applied_history: list[AppliedDeltaRecord] = list(
                self.session.applied_history
            )
            self._seed_logs = list(self.session.logs)
            self._log_lines = list(self.session.logs)
            self._runtime_boot_thread: threading.Thread | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Vertical(id="root"):
                yield Static("", id="status-strip")
                with Horizontal(id="task-bar"):
                    yield Input(
                        placeholder="Tell Forge what to change...", id="task-input"
                    )
                    yield Input(
                        placeholder="Optional files: app.py tests/test_app.py",
                        id="files-input",
                    )
                with Horizontal(id="control-bar"):
                    yield Button("Run", id="run-button", variant="primary")
                    yield Button("Step", id="step-button")
                    yield Button("Stop", id="stop-button", variant="error")
                    yield Button("Check Runtime", id="runtime-button")
                    yield Button("Palette", id="palette-button")
                    yield Checkbox("Auto loop", value=False, id="auto-checkbox")
                    yield Checkbox("Apply", value=True, id="apply-checkbox")
                    yield Checkbox("Planner", value=False, id="planner-checkbox")
                    yield Checkbox("Model redteam", value=False, id="redteam-checkbox")
                    yield Checkbox("Debug", value=False, id="debug-checkbox")
                with Horizontal(id="row-top"):
                    with Vertical(id="control-pane"):
                        yield Static("Φ / MODE", classes="section")
                        yield Static("", id="control-summary")
                        yield Static("Live candidates", classes="section")
                        yield OptionList(id="candidate-list")
                        yield Static("Recent runs", classes="section")
                        yield OptionList(id="history-list")
                        yield Static("", id="files-view")
                        yield Static("COMMANDS", classes="section")
                        yield Static(render_command_legend(), id="legend-view")
                    with Vertical(id="diff-pane"):
                        yield Static("DIFF VIEW", classes="section")
                        yield Static(
                            "Use Palette for run / step / accept / export",
                            id="diff-hint",
                            classes="hint",
                        )
                        yield TextArea(
                            "", language="diff", read_only=True, id="diff-view"
                        )
                with Horizontal(id="row-mid"):
                    with Vertical(id="redteam-pane"):
                        yield Static("REDTEAM", classes="section")
                        yield Static("", id="redteam-view")
                    with Vertical(id="tests-pane"):
                        yield Static("TESTS", classes="section")
                        yield Static("", id="tests-view")
                with Vertical(id="logs-pane"):
                    yield Static("LOGS / EVENTS", classes="section")
                    yield Log(id="log-view")
                    yield Input(
                        placeholder=": run | : step | : mode tri | : tau 0.25",
                        id="command-input",
                    )
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#task-input", Input).value = self.session.task_text
            self.query_one("#files-input", Input).value = self.session.files_text
            self.query_one("#auto-checkbox", Checkbox).value = bool(
                self.session.controls.get("auto", False)
            )
            self.query_one("#apply-checkbox", Checkbox).value = bool(
                self.session.controls.get("apply", True)
            )
            self.query_one("#planner-checkbox", Checkbox).value = bool(
                self.session.controls.get("planner", False)
            )
            self.query_one("#redteam-checkbox", Checkbox).value = bool(
                self.session.controls.get("redteam", False)
            )
            self.query_one("#debug-checkbox", Checkbox).value = bool(
                self.session.controls.get("debug", False)
            )
            for line in self._seed_logs:
                self.query_one("#log-view", Log).write_line(line)
            self._refresh_runtime(auto_boot=True)
            self._refresh_history()
            if self.session.selected_record_id is not None:
                selected_index = _find_history_index(
                    self.history, self.session.selected_record_id
                )
                if selected_index is not None:
                    self.selected_record = self.history[selected_index]
            self._render_panels()
            if not self._seed_logs:
                self._log("Type a task and press Run. Use : for the command palette.")
            if self.machine_state.get("stage_label") == "warming ai":
                self._log(_runtime_doctor_message(self.runtime_summary))
            self.query_one("#task-input", Input).focus()

        def action_open_palette(self) -> None:
            command = self.query_one("#command-input", Input)
            command.display = True
            command.value = ""
            command.focus()
            self._log("Palette open. Example: : mode tri")

        def action_toggle_auto_loop(self) -> None:
            checkbox = self.query_one("#auto-checkbox", Checkbox)
            checkbox.value = not checkbox.value
            self._log(f"Auto loop {'on' if checkbox.value else 'off'}")

        def action_toggle_planner(self) -> None:
            checkbox = self.query_one("#planner-checkbox", Checkbox)
            checkbox.value = not checkbox.value
            self._log(f"Planner {'on' if checkbox.value else 'off'}")

        def action_toggle_redteam(self) -> None:
            checkbox = self.query_one("#redteam-checkbox", Checkbox)
            checkbox.value = not checkbox.value
            self._log(f"Model redteam {'on' if checkbox.value else 'off'}")

        def action_toggle_redteam_details(self) -> None:
            self.redteam_expanded = not self.redteam_expanded
            self._render_panels()
            self._log(
                f"Redteam details {'expanded' if self.redteam_expanded else 'collapsed'}"
            )

        def action_toggle_tests(self) -> None:
            self.tests_expanded = not self.tests_expanded
            self._log(
                f"Test details {'expanded' if self.tests_expanded else 'collapsed'}"
            )
            self._render_panels()

        def action_show_ban_hits(self) -> None:
            self._log(f"Ban hits: {self.machine_state.get('ban_hits', 0)}")

        def action_expand_context_hint(self) -> None:
            self._handle_command("expand")

        def action_safe_revert(self) -> None:
            self._handle_command("revert")

        def action_cycle_mode(self) -> None:
            modes = ["AUTO", "SIMPLE", "BISECT", "TRISECT"]
            current = str(self.machine_state.get("mode_override", "AUTO"))
            index = modes.index(current) if current in modes else 0
            next_mode = modes[(index + 1) % len(modes)]
            self.machine_state["mode_override"] = next_mode
            self.machine_state["mode"] = next_mode
            self._render_panels()
            self._log(f"Mode override: {next_mode}")

        def action_next_diff(self) -> None:
            if self.live_candidates:
                self._cycle_candidate_selection()
                return
            if not self.history:
                return
            option_list = self.query_one("#history-list", OptionList)
            current = option_list.highlighted or 0
            option_list.highlighted = (current + 1) % len(self.history)
            self._show_record(option_list.highlighted)

        def action_step_run(self) -> None:
            self._start_run(auto=False)

        @on(Button.Pressed, "#run-button")
        def _on_run_pressed(self) -> None:
            self._start_run(auto=self.query_one("#auto-checkbox", Checkbox).value)

        @on(Button.Pressed, "#step-button")
        def _on_step_pressed(self) -> None:
            self._start_run(auto=False)

        @on(Button.Pressed, "#stop-button")
        def _on_stop_pressed(self) -> None:
            self.stop_requested = True
            self.machine_state["status"] = "RUNNING"
            self.machine_state["stage_label"] = "stop requested"
            self._render_panels()
            self._log("Stop requested. Forge will stop after the current iteration.")

        @on(Button.Pressed, "#runtime-button")
        def _on_runtime_pressed(self) -> None:
            self._refresh_runtime(auto_boot=True, force_boot=True)
            self._render_panels()

        @on(Button.Pressed, "#palette-button")
        def _on_palette_pressed(self) -> None:
            self.action_open_palette()

        @on(Input.Submitted, "#task-input")
        def _on_task_submitted(self) -> None:
            self._start_run(auto=False)

        @on(Input.Submitted, "#command-input")
        def _on_command_submitted(self, event: Input.Submitted) -> None:
            event.stop()
            command = event.value.strip()
            palette = self.query_one("#command-input", Input)
            palette.value = ""
            palette.display = False
            self.query_one("#task-input", Input).focus()
            if not command:
                return
            self._handle_command(command)

        @on(OptionList.OptionSelected, "#history-list")
        def _on_history_selected(self, event: OptionList.OptionSelected) -> None:
            self._show_record(event.index)

        @on(OptionList.OptionSelected, "#candidate-list")
        def _on_candidate_selected(self, event: OptionList.OptionSelected) -> None:
            self._show_candidate_by_index(event.index)

        @work(thread=True, exclusive=True, group="forge-run")
        def _run_worker(self, request: RunRequest) -> None:
            attempts = 0
            max_attempts = 4 if request.auto_loop else 1
            self.stop_requested = False
            self.call_from_thread(self._set_running_state, True)
            while attempts < max_attempts and not self.stop_requested:
                attempts += 1
                self.call_from_thread(self._set_stage, "RUNNING", f"iter {attempts}")
                client, runtime_summary = _build_client_from_request(request)
                self.call_from_thread(self._set_runtime_summary, runtime_summary)
                if client is None or not getattr(client, "enabled", True):
                    self.call_from_thread(
                        self._set_stage, "WAITING", "runtime warming"
                    )
                    self.call_from_thread(
                        self._log, _runtime_doctor_message(runtime_summary)
                    )
                    break
                orchestrator = ForgeOrchestrator(
                    request.repo_root,
                    apply_accepted=request.apply_accepted,
                    client=client,
                )

                def sink(payload: dict[str, Any]) -> None:
                    self.call_from_thread(self._handle_event, payload)

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
                        event_sink=sink,
                    )
                except (
                    Exception
                ) as exc:  # pragma: no cover - safety net for interactive mode
                    self.call_from_thread(
                        self._set_stage, "WAITING", "run needs review"
                    )
                    self.call_from_thread(
                        self._log,
                        f"Run failed; moved to manual review ({type(exc).__name__}).",
                    )
                    break
                self.call_from_thread(self._record_result, result)
                if not request.auto_loop or result["status"] == "promote":
                    break
            self.call_from_thread(self._set_running_state, False)
            if self.stop_requested:
                self.call_from_thread(self._set_stage, "INTERRUPTED", "interrupted")
                self.call_from_thread(self._log, "Forge stopped by operator.")

        def _start_run(self, *, auto: bool) -> None:
            if self.running:
                self._log("Forge is already running.")
                return
            request = self._build_request(auto=auto)
            if request is None:
                return
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
            self.session.resume_request = _request_payload(request)
            self._refresh_candidate_list()
            self._render_panels()
            self._run_worker(request)

        def _build_request(self, *, auto: bool) -> RunRequest | None:
            task_text = self.query_one("#task-input", Input).value.strip()
            if not task_text:
                self._log("Type a task first, like: fix the failing tests")
                return None
            files = tuple(_split_files(self.query_one("#files-input", Input).value))
            apply_accepted = self.query_one("#apply-checkbox", Checkbox).value
            planner_enabled = self.query_one("#planner-checkbox", Checkbox).value
            redteam_enabled = self.query_one("#redteam-checkbox", Checkbox).value
            debug_enabled = self.query_one("#debug-checkbox", Checkbox).value
            auto_loop = auto
            mode_override = str(
                self.machine_state.get(
                    "mode_override", DEFAULT_UI_STATE_CONFIG.mode_override
                )
            )
            risk_threshold = float(
                self.machine_state.get(
                    "risk_threshold", DEFAULT_UI_STATE_CONFIG.risk_threshold
                )
            )
            context_level = int(
                self.machine_state.get(
                    "context_level", DEFAULT_UI_STATE_CONFIG.context_level
                )
            )
            test_mode = str(
                self.machine_state.get("test_mode", DEFAULT_UI_STATE_CONFIG.test_mode)
            )
            return RunRequest(
                task_text=task_text,
                files=files,
                repo_root=self.repo_root,
                apply_accepted=apply_accepted,
                planner_enabled=planner_enabled,
                redteam_enabled=redteam_enabled,
                debug_enabled=debug_enabled,
                auto_loop=auto_loop,
                mode_override=mode_override,
                risk_threshold=risk_threshold,
                context_level=context_level,
                test_mode=test_mode,
                timeout_s=self.timeout_s,
                num_ctx=self.num_ctx,
                preferred_model=self.preferred_model,
                preferred_url=self.preferred_url,
            )

        def _refresh_runtime(
            self,
            *,
            auto_boot: bool = False,
            force_boot: bool = False,
        ) -> None:
            status = detect_runtime_status(
                preferred_url=self.preferred_url,
                preferred_model=self.preferred_model,
            )
            self._apply_runtime_status(status)
            if auto_boot and not status.ready:
                self._start_runtime_boot(force=force_boot)

        def _apply_runtime_status(self, status: RuntimeStatus) -> None:
            self.runtime_status = status
            self.runtime_summary = status.summary
            self.machine_state["runtime"] = status.as_dict()
            self.machine_state["runtime_endpoint"] = status.endpoint
            self.machine_state["runtime_model"] = status.model
            self.machine_state["runtime_models"] = list(status.models)
            if not status.ready:
                self.machine_state["status"] = "WAITING"
                self.machine_state["stage_label"] = "warming ai"
            elif self.machine_state.get("stage_label") == "warming ai":
                self.machine_state["status"] = "WAITING"
                self.machine_state["stage_label"] = "idle"
            self._log(status.summary)

        def _start_runtime_boot(self, *, force: bool) -> None:
            if (
                self._runtime_boot_thread is not None
                and self._runtime_boot_thread.is_alive()
            ):
                return
            if not force and bool(self.machine_state.get("runtime_boot_attempted")):
                return
            self.machine_state["runtime_boot_attempted"] = True
            self._runtime_boot_thread = threading.Thread(
                target=self._runtime_boot_worker,
                daemon=True,
            )
            self._runtime_boot_thread.start()

        def _runtime_boot_worker(self) -> None:
            self._log("Forge is waking up the local AI in the background.")
            status = ensure_runtime_ready(
                preferred_url=self.preferred_url,
                preferred_model=self.preferred_model,
            )
            self.call_from_thread(self._apply_runtime_status, status)
            for action in status.actions:
                self.call_from_thread(self._log, action)
            for detail in status.nerd_details:
                self.call_from_thread(self._log, detail)
            self.call_from_thread(
                self._log,
                status.message if not status.ready else "Local AI is ready.",
            )

        def _refresh_history(self) -> None:
            self.history = load_history_records(artifacts_dir_for_repo(self.repo_root))
            option_list = self.query_one("#history-list", OptionList)
            selected_identifier = (
                self.selected_record.identifier
                if self.selected_record is not None
                else self.session.selected_record_id
            )
            option_list.clear_options()
            if self.history:
                option_list.add_options([record.label for record in self.history])
                selected_index = _find_history_index(self.history, selected_identifier)
                if selected_index is None:
                    selected_index = 0
                option_list.highlighted = selected_index
                if self.selected_candidate_id is None:
                    self.selected_record = self.history[selected_index]
            else:
                self.selected_record = None

        def _record_result(self, result: dict[str, Any]) -> None:
            record = history_record_from_result(result)
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
            self._refresh_history()
            selected_candidate = str(result.get("delta_id") or "")
            if selected_candidate and selected_candidate in self.live_candidates:
                self._show_candidate(selected_candidate)
            elif self.selected_candidate_id is None:
                self._show_record(0)
            if bool(result.get("applied")) and record.diff_text.startswith(
                "diff --git "
            ):
                self._remember_applied_patch(
                    label=f"auto-applied {record.identifier}",
                    patch=record.diff_text,
                    files_touched=record.files_touched,
                    source="auto_apply",
                    task=str(self.machine_state.get("task", "")),
                    identifier=str(result.get("delta_id") or record.identifier),
                    patch_path=str(record.patch_path)
                    if record.patch_path is not None
                    else None,
                )
            self._render_panels()
            self._log(f"{result['status']}: {result['detail']}")

        def _show_record(self, index: int) -> None:
            if index < 0 or index >= len(self.history):
                return
            self.selected_candidate_id = None
            self.session.selected_candidate_id = None
            self.selected_record = self.history[index]
            self.session.selected_record_id = self.selected_record.identifier
            self._render_panels()

        def _show_candidate_by_index(self, index: int) -> None:
            candidate_ids = list(self.live_candidates)
            if index < 0 or index >= len(candidate_ids):
                return
            self._show_candidate(candidate_ids[index])

        def _show_candidate(self, candidate_id: str) -> None:
            if candidate_id not in self.live_candidates:
                return
            self.selected_candidate_id = candidate_id
            self.selected_record = None
            self.session.selected_candidate_id = candidate_id
            self.session.selected_record_id = None
            self._render_panels()

        def _render_panels(self) -> None:
            debug = self.query_one("#debug-checkbox", Checkbox).value
            record = self._current_panel_record()
            self.query_one("#status-strip", Static).update(
                render_status_strip(
                    self.runtime_summary,
                    self.machine_state,
                    live_count=len(self.live_candidates),
                    history_count=len(self.history),
                    selected_label=_selected_label(record),
                )
            )
            self.query_one("#control-summary", Static).update(
                render_control_panel(
                    self.runtime_summary, self.machine_state, record, debug=debug
                )
            )
            self.query_one("#files-view", Static).update(render_files_panel(record))
            self.query_one("#redteam-view", Static).update(
                render_redteam_panel(record, expanded=self.redteam_expanded or debug)
            )
            self.query_one("#tests-view", Static).update(
                render_test_panel(record, expanded=self.tests_expanded or debug)
            )
            self.query_one("#diff-view", TextArea).load_text(_record_diff_text(record))
            self._refresh_candidate_list()
            self._refresh_history_highlight()
            self._persist_session()

        def _handle_event(self, event: dict[str, Any]) -> None:
            stage = str(event.get("stage", "event"))
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
            self._render_panels()
            self._log(f"[{stage}] {event.get('message', '')}")

        def _set_running_state(self, running: bool) -> None:
            self.running = running
            if running:
                self.machine_state["status"] = "RUNNING"
                self.machine_state["stage_label"] = "running"
            elif self.machine_state.get("status") == "RUNNING":
                self.machine_state["status"] = "WAITING"
                if self.machine_state.get("stage") in {"queued", "idle"}:
                    self.machine_state["stage_label"] = "idle"
            self._render_panels()

        def _set_stage(self, status: str, label: str) -> None:
            self.machine_state["status"] = status
            self.machine_state["stage_label"] = label
            self.machine_state["last_event"] = label
            self._render_panels()

        def _set_runtime_summary(self, runtime_summary: str) -> None:
            self.runtime_summary = runtime_summary
            if "not detected" in runtime_summary.lower():
                self.machine_state["status"] = "WAITING"
                self.machine_state["stage_label"] = "warming ai"
            self._render_panels()

        def _log(self, message: str) -> None:
            self.query_one("#log-view", Log).write_line(message)
            self._log_lines.append(message)
            self._log_lines = self._log_lines[-500:]
            self._persist_session()

        def _handle_command(self, command: str) -> None:
            parsed = _parse_command(command)
            if parsed is None:
                return
            raw, cmd, args = parsed
            if self._dispatch_immediate_command(cmd, args):
                return
            if self._dispatch_setting_command(cmd, args):
                return
            self._log(f"Unknown command: {raw}")

        def _dispatch_immediate_command(self, cmd: str, args: list[str]) -> bool:
            if cmd == "run":
                self._start_run(auto=True)
                return True
            if cmd == "step":
                self._start_run(auto=False)
                return True
            if cmd == "resume":
                self._resume_last_request()
                return True
            if cmd == "stop":
                self.stop_requested = True
                self._log("Stop requested.")
                return True
            if cmd == "accept":
                self._accept_selected_patch()
                return True
            if cmd == "reject":
                self._reject_selection()
                return True
            if cmd == "revert":
                self._apply_safe_revert() if args and args[
                    0
                ] == "apply" else self._preview_safe_revert()
                return True
            if cmd == "export":
                self._export_state()
                return True
            if cmd == "quit":
                self.exit()
                return True
            return False

        def _dispatch_setting_command(self, cmd: str, args: list[str]) -> bool:
            if cmd == "mode" and args:
                self._set_mode_override(args[0])
                return True
            if cmd == "plan" and args:
                self._toggle_checkbox("#planner-checkbox", "Planner", args[0] == "on")
                return True
            if cmd == "tau" and args:
                self._set_tau(args[0])
                return True
            if cmd == "redteam" and args:
                self._toggle_checkbox(
                    "#redteam-checkbox", "Model redteam", args[0] == "on"
                )
                return True
            if cmd == "tests" and args:
                self._set_test_mode(args[0])
                return True
            if cmd in {"expand", "shrink"}:
                self._adjust_context(1 if cmd == "expand" else -1)
                return True
            if cmd == "debug" and args:
                self._toggle_checkbox(
                    "#debug-checkbox", "Debug", args[0] == "on", rerender=True
                )
                return True
            return False

        def _reject_selection(self) -> None:
            if (
                self.selected_candidate_id is not None
                and self.selected_candidate_id in self.live_candidates
            ):
                rejected = self.selected_candidate_id
                del self.live_candidates[rejected]
                self.selected_candidate_id = None
                if self.live_candidates:
                    self._show_candidate(next(iter(self.live_candidates)))
                self._log(f"Rejected live candidate {rejected}.")
            else:
                self._log("Reject cleared the current selection.")
                self.selected_record = None
            self._render_panels()

        def _toggle_checkbox(
            self, selector: str, label: str, enabled: bool, *, rerender: bool = False
        ) -> None:
            self.query_one(selector, Checkbox).value = enabled
            if rerender:
                self._render_panels()
            self._log(f"{label} {'on' if enabled else 'off'}")

        def _accept_selected_patch(self) -> None:
            if (
                self.selected_candidate_id is not None
                and self.selected_candidate_id in self.live_candidates
            ):
                candidate = self.live_candidates[self.selected_candidate_id]
                if not candidate.patch:
                    self._log("That live candidate has no patch payload.")
                    return
                try:
                    apply_unified_diff(self.repo_root, candidate.patch)
                except ValueError as exc:
                    self._log(f"Could not apply live patch: {exc}")
                    return
                self._remember_applied_patch(
                    label=f"live candidate {candidate.identifier}",
                    patch=candidate.patch,
                    files_touched=candidate.files_touched,
                    source="live_candidate",
                    task=str(self.machine_state.get("task", "")),
                    identifier=candidate.identifier,
                )
                self._log(f"Applied live candidate {candidate.identifier}")
                return
            if self.selected_record is None or self.selected_record.patch_path is None:
                self._log("No accepted patch is selected.")
                return
            if bool(self.selected_record.payload.get("applied")):
                self._log("That patch was already applied.")
                return
            try:
                apply_unified_diff(self.repo_root, self.selected_record.diff_text)
            except ValueError as exc:
                self._log(f"Could not apply patch: {exc}")
                return
            self._remember_applied_patch(
                label=f"history patch {self.selected_record.identifier}",
                patch=self.selected_record.diff_text,
                files_touched=self.selected_record.files_touched,
                source="history_patch",
                task=str(self.machine_state.get("task", "")),
                identifier=self.selected_record.identifier,
                patch_path=str(self.selected_record.patch_path),
            )
            self._log(f"Applied patch from {self.selected_record.patch_path}")

        def _set_mode_override(self, value: str) -> None:
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
                return
            self.machine_state["mode_override"] = mapping[value]
            self.machine_state["mode"] = mapping[value]
            self._render_panels()
            self._log(f"Mode override: {mapping[value]}")

        def _set_tau(self, value: str) -> None:
            try:
                parsed = max(0.0, min(1.0, float(value)))
            except ValueError:
                self._log("Tau must be a number between 0 and 1.")
                return
            self.machine_state["risk_threshold"] = parsed
            self._render_panels()
            self._log(f"Risk threshold set to {parsed:.2f}")

        def _export_state(self) -> None:
            export_path = self.repo_root / ".forge" / "ui-export.json"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._session_snapshot()
            export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._log(f"Exported UI state to {export_path}")

        def _resume_last_request(self) -> None:
            request_payload = self.session.resume_request
            if not request_payload:
                self._log("No paused task is ready to resume yet.")
                return
            self.query_one("#task-input", Input).value = str(
                request_payload.get("task_text", "")
            )
            self.query_one("#files-input", Input).value = " ".join(
                request_payload.get("files", [])
            )
            self.machine_state["context_level"] = int(
                request_payload.get(
                    "context_level", self.machine_state.get("context_level", 0)
                )
            )
            self.machine_state["test_mode"] = str(
                request_payload.get(
                    "test_mode", self.machine_state.get("test_mode", "default")
                )
            )
            self._start_run(auto=bool(request_payload.get("auto_loop", False)))

        def _adjust_context(self, delta: int) -> None:
            current = int(self.machine_state.get("context_level", 0))
            updated = max(0, min(3, current + delta))
            if updated == current:
                self._log(f"Context already at level {current}.")
                return
            self.machine_state["context_level"] = updated
            files = 6 + updated * 2
            excerpt = 1200 + updated * 800
            self._render_panels()
            self._log(
                f"Context level {updated}: up to {files} files, excerpt budget {excerpt} chars."
            )

        def _set_test_mode(self, value: str) -> None:
            if value not in {"default", "fast", "full"}:
                self._log("Test mode must be default, fast, or full.")
                return
            self.machine_state["test_mode"] = value
            self._render_panels()
            if value == "fast":
                self._log(
                    "Test mode fast: Forge will target explicit test files when possible."
                )
            else:
                self._log(f"Test mode {value} enabled.")

        def _preview_safe_revert(self) -> None:
            if not self.applied_history:
                self._log("Nothing in Forge lineage is ready to revert.")
                return
            latest = self.applied_history[-1]
            touched = ", ".join(latest.files_touched[:4]) or "unknown files"
            self._log(
                f"Ready to revert {latest.label} touching {touched}. "
                "Run : revert apply to undo it."
            )

        def _apply_safe_revert(self) -> None:
            if not self.applied_history:
                self._log("Nothing in Forge lineage is ready to revert.")
                return
            latest = self.applied_history[-1]
            try:
                apply_unified_diff(self.repo_root, latest.revert_patch)
            except ValueError as exc:
                self._log(f"Could not revert {latest.label}: {exc}")
                return
            self.applied_history.pop()
            self.machine_state["status"] = "WAITING"
            self.machine_state["stage_label"] = "reverted"
            self.machine_state["last_event"] = f"reverted {latest.identifier}"
            self._render_panels()
            self._log(f"Reverted {latest.label}")

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
                identifier=identifier or delta_id(patch),
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
            self._persist_session()

        def _session_snapshot(self) -> dict[str, Any]:
            return {
                "runtime_summary": self.runtime_summary,
                "machine_state": dict(self.machine_state),
                "controls": self._controls_snapshot(),
                "task_text": self.query_one("#task-input", Input).value,
                "files_text": self.query_one("#files-input", Input).value,
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
                "applied_history": [item.as_dict() for item in self.applied_history],
                "resume_request": self.session.resume_request,
            }

        def _controls_snapshot(self) -> dict[str, Any]:
            return {
                "auto": self.query_one("#auto-checkbox", Checkbox).value,
                "apply": self.query_one("#apply-checkbox", Checkbox).value,
                "planner": self.query_one("#planner-checkbox", Checkbox).value,
                "redteam": self.query_one("#redteam-checkbox", Checkbox).value,
                "debug": self.query_one("#debug-checkbox", Checkbox).value,
                "mode_override": str(
                    self.machine_state.get(
                        "mode_override", DEFAULT_UI_STATE_CONFIG.mode_override
                    )
                ),
                "risk_threshold": float(
                    self.machine_state.get(
                        "risk_threshold", DEFAULT_UI_STATE_CONFIG.risk_threshold
                    )
                ),
                "context_level": int(
                    self.machine_state.get(
                        "context_level", DEFAULT_UI_STATE_CONFIG.context_level
                    )
                ),
                "test_mode": str(
                    self.machine_state.get(
                        "test_mode", DEFAULT_UI_STATE_CONFIG.test_mode
                    )
                ),
            }

        def _persist_session(self) -> None:
            self.session.task_text = self.query_one("#task-input", Input).value
            self.session.files_text = self.query_one("#files-input", Input).value
            self.session.controls = self._controls_snapshot()
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
            self.session.logs = list(self._log_lines)[-500:]
            self.session.applied_history = list(self.applied_history)
            save_session(self.session_path, self.session)

        def _refresh_candidate_list(self) -> None:
            option_list = self.query_one("#candidate-list", OptionList)
            selected_id = self.selected_candidate_id
            option_list.clear_options()
            if not self.live_candidates:
                return
            option_list.add_options(
                [candidate.label for candidate in self.live_candidates.values()]
            )
            selected_index = _find_candidate_index(self.live_candidates, selected_id)
            if selected_index is None:
                selected_index = 0
                self.selected_candidate_id = list(self.live_candidates)[0]
            option_list.highlighted = selected_index

        def _refresh_history_highlight(self) -> None:
            option_list = self.query_one("#history-list", OptionList)
            if not self.history:
                return
            if self.selected_record is None:
                option_list.highlighted = 0
                return
            selected_index = _find_history_index(
                self.history, self.selected_record.identifier
            )
            if selected_index is not None:
                option_list.highlighted = selected_index

        def _current_panel_record(self) -> HistoryRecord | CandidateRecord | None:
            if self.selected_candidate_id is not None:
                candidate = self.live_candidates.get(self.selected_candidate_id)
                if candidate is not None:
                    return candidate
            return self.selected_record

        def _cycle_candidate_selection(self) -> None:
            candidate_ids = list(self.live_candidates)
            if not candidate_ids:
                return
            if self.selected_candidate_id in self.live_candidates:
                current_index = candidate_ids.index(self.selected_candidate_id)
                next_index = (current_index + 1) % len(candidate_ids)
            else:
                next_index = 0
            self._show_candidate(candidate_ids[next_index])

        def _update_candidate_from_event(
            self, stage: str, event: dict[str, Any]
        ) -> None:
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
            patch = str(event.get("patch", candidate.patch))
            files_touched = tuple(event.get("files_touched", candidate.files_touched))
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
                patch=patch,
                files_touched=files_touched,
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
                coverage_delta=float(
                    event.get("coverage_delta", candidate.coverage_delta)
                ),
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

    ForgeApp().run()
    return 0


_split_files = split_files
_stage_label = stage_label
_status_from_result = status_from_result
_event_status = event_status
_candidate_status = candidate_status
_record_diff_text = record_diff_text
_selected_label = selected_label
_find_candidate_index = find_candidate_index
_find_history_index = find_history_index
_task_identifier = task_identifier
_candidate_payload = candidate_payload
_candidate_from_payload = candidate_from_payload
_request_payload = request_payload
_build_client_from_request = build_client_from_request
_runtime_doctor_message = runtime_doctor_message
