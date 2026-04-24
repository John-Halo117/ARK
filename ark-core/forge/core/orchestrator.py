"""CLI-facing Forge orchestrator."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ..context.provider import ContextProvider, DefaultContextProvider
from ..exec.git import resolve_lkg_id
from ..exec.runner import project_python, run_command
from ..memory.store import default_state_path, load_state, save_state
from ..models.ollama_client import OllamaClient, OllamaConfig, OllamaError
from ..runtime.artifacts import write_task_artifacts
from ..runtime.config import DEFAULT_POLICY_CONFIG
from ..transform.apply import apply_unified_diff
from ..types import ForgeTask
from ..verify.adapters import PythonVerifierAdapter, VerifierAdapter
from .loop import run_task

ENGINE_ROOT = Path(__file__).resolve().parents[2]


def load_tasks(path: Path) -> list[ForgeTask]:
    """Load bounded task items from JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload["tasks"] if isinstance(payload, dict) else payload
    tasks: list[ForgeTask] = []
    for idx, item in enumerate(raw_items):
        tasks.append(
            ForgeTask(
                identifier=item.get("id", f"task-{idx + 1}"),
                summary=item["summary"],
                scope=item["scope"],
                todo=item["todo"],
                target_files=tuple(item.get("target_files", [])),
                constraints=tuple(item.get("constraints", [])),
                patch=item.get("patch"),
            )
        )
    return tasks


class ForgeOrchestrator:
    """Contained self-coding engine for ARK."""

    def __init__(
        self,
        repo_root: Path,
        *,
        state_path: Path | None = None,
        artifacts_dir: Path | None = None,
        apply_accepted: bool = False,
        client: OllamaClient | None = None,
        context_provider: ContextProvider | None = None,
        verifier: VerifierAdapter | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.tool_root = ENGINE_ROOT
        self.state_path = state_path or default_state_path(repo_root)
        self.artifacts_dir = artifacts_dir or self.state_path.parent / "artifacts"
        self.apply_accepted = apply_accepted
        self.state, self.banlist = load_state(
            self.state_path, fallback_lkg=resolve_lkg_id(repo_root)
        )
        self.client = client or OllamaClient()
        self.context_provider = context_provider or DefaultContextProvider()
        self.verifier = verifier or PythonVerifierAdapter()

    def process(
        self,
        task: ForgeTask,
        *,
        dry_run: bool,
        mode_override: str | None = None,
        risk_threshold: float = DEFAULT_POLICY_CONFIG.risk_threshold,
        event_sink: object | None = None,
    ) -> dict[str, object]:
        """Run one task through tiering and, when allowed, the Forge loop."""

        _emit(
            event_sink,
            "classify_start",
            f"classifying {task.identifier}",
            task_id=task.identifier,
        )
        ollama_status = self._ollama_status()
        classification = _classify_task(
            task, self.repo_root, python_bin=project_python(self.tool_root)
        )
        if not classification["ok"]:
            return self._blocked_payload(
                task.identifier,
                classification["stderr"] or classification["stdout"],
                event_sink=event_sink,
                classification=classification,
                ollama_status=ollama_status,
            )
        runtime_error, ollama_status = self._require_runtime(
            task, dry_run=dry_run, event_sink=event_sink, ollama_status=ollama_status
        )
        if runtime_error is not None:
            return self._blocked_payload(
                task.identifier,
                runtime_error,
                event_sink=event_sink,
                ollama_status=ollama_status,
            )
        try:
            execution = self._execute_task(
                task,
                dry_run=dry_run,
                mode_override=mode_override,
                risk_threshold=risk_threshold,
                event_sink=event_sink,
            )
        except OllamaError as exc:
            return self._blocked_payload(
                task.identifier,
                str(exc),
                event_sink=event_sink,
                ollama_status=ollama_status,
            )
        return self._complete_payload(
            task.identifier,
            execution,
            risk_threshold=risk_threshold,
            ollama_status=ollama_status,
            event_sink=event_sink,
        )

    def _apply_accepted_patch(
        self,
        result: dict[str, object],
        patch: str,
    ) -> tuple[bool, dict[str, object]]:
        try:
            apply_unified_diff(self.repo_root, patch)
        except ValueError as exc:
            result["status"] = "manual_review"
            result["detail"] = f"accepted delta could not be applied to the repo: {exc}"
            return False, result
        self.state.lkg_id = resolve_lkg_id(self.repo_root)
        result["lkg_id"] = self.state.lkg_id
        metrics = dict(result.get("metrics", {}))
        metrics["lkg_id"] = self.state.lkg_id
        result["metrics"] = metrics
        return True, result

    def _persist_result(
        self,
        task_id: str,
        result: dict[str, object],
        accepted_patch: str | None,
    ) -> dict[str, object]:
        artifacts = write_task_artifacts(
            self.artifacts_dir,
            task_id=task_id,
            sequence=int(self.state.attempt),
            result_payload=result,
            accepted_patch=accepted_patch,
        )
        payload = dict(result)
        payload["artifacts"] = artifacts
        return payload

    def _ollama_status(self) -> dict[str, object]:
        return self.client.check() if self.client.enabled else self.client.as_dict()

    def _require_runtime(
        self,
        task: ForgeTask,
        *,
        dry_run: bool,
        event_sink: object | None,
        ollama_status: dict[str, object],
    ) -> tuple[str | None, dict[str, object]]:
        if not self.client.enabled or task.patch is not None or dry_run:
            return None, ollama_status
        try:
            _emit(
                event_sink,
                "runtime_check",
                "checking Ollama readiness",
                task_id=task.identifier,
            )
            return None, self.client.require_ready()
        except OllamaError as exc:
            return str(exc), ollama_status

    def _execute_task(
        self,
        task: ForgeTask,
        *,
        dry_run: bool,
        mode_override: str | None,
        risk_threshold: float,
        event_sink: object | None,
    ):
        return run_task(
            task,
            self.repo_root,
            self.state,
            self.banlist,
            self.client,
            tool_root=self.tool_root,
            dry_run=dry_run,
            mode_override=mode_override,
            context_provider=self.context_provider,
            verifier=self.verifier,
            risk_threshold=risk_threshold,
            event_sink=event_sink,
        )

    def _complete_payload(
        self,
        task_id: str,
        execution,
        *,
        risk_threshold: float,
        ollama_status: dict[str, object],
        event_sink: object | None,
    ) -> dict[str, object]:
        result = execution.result.as_dict()
        accepted_patch = (
            execution.accepted_candidate.patch
            if execution.accepted_candidate is not None
            else None
        )
        result["metrics"] = self._result_metrics(
            execution,
            result,
            risk_threshold=risk_threshold,
            ollama_status=ollama_status,
        )
        applied, result = self._maybe_apply_accepted_patch(
            execution, result, accepted_patch, event_sink=event_sink
        )
        result["applied"] = applied
        payload = self._persist_and_save(task_id, result, accepted_patch)
        _emit(
            event_sink,
            "complete",
            f"{result['status']}: {result['detail']}",
            status=result["status"],
            applied=applied,
        )
        return payload

    def _result_metrics(
        self,
        execution,
        result: dict[str, object],
        *,
        risk_threshold: float,
        ollama_status: dict[str, object],
    ) -> dict[str, object]:
        metrics = dict(result.get("metrics", {}))
        metrics["ollama"] = ollama_status
        metrics["risk_threshold"] = risk_threshold
        if execution.accepted_candidate is not None:
            metrics["files_touched"] = list(execution.accepted_candidate.files_touched)
            metrics["strategy"] = execution.accepted_candidate.strategy
            metrics["seed"] = execution.accepted_candidate.seed
        if execution.best_evaluation is not None:
            metrics["best_candidate"] = _evaluation_snapshot(execution.best_evaluation)
        if execution.accepted_evaluation is not None:
            metrics["verify"] = _verify_snapshot(execution.accepted_evaluation)
            metrics["critique"] = _critique_snapshot(execution.accepted_evaluation)
        return metrics

    def _maybe_apply_accepted_patch(
        self,
        execution,
        result: dict[str, object],
        accepted_patch: str | None,
        *,
        event_sink: object | None,
    ) -> tuple[bool, dict[str, object]]:
        if (
            not self.apply_accepted
            or execution.result.status != "promote"
            or accepted_patch is None
        ):
            return False, result
        _emit(
            event_sink,
            "apply",
            f"applying accepted delta {execution.accepted_candidate.identifier}",
            delta_id=execution.accepted_candidate.identifier,
        )
        return self._apply_accepted_patch(result, accepted_patch)

    def _blocked_payload(
        self,
        task_id: str,
        detail: str,
        *,
        event_sink: object | None,
        classification: dict[str, object] | None = None,
        ollama_status: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metrics = {"task_id": task_id}
        if classification is not None:
            metrics["classification"] = classification
        if ollama_status is not None:
            metrics["ollama"] = ollama_status
        result = {
            "identifier": task_id,
            "status": "manual_review",
            "detail": detail,
            "engine": "forge",
            "lkg_id": self.state.lkg_id,
            "mode": "SIMPLE",
            "phi": 0.0,
            "risk": 1.0,
            "applied": False,
            "metrics": metrics,
            "artifacts": {},
        }
        payload = self._persist_and_save(task_id, result, None)
        _emit(event_sink, "blocked", detail, status=result["status"])
        return payload

    def _persist_and_save(
        self, task_id: str, result: dict[str, object], accepted_patch: str | None
    ) -> dict[str, object]:
        payload = self._persist_result(task_id, result, accepted_patch)
        save_state(self.state_path, self.state, self.banlist)
        return payload


def cli_main() -> int:
    """Entry point used by scripts/ai/orchestrator.py."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks", type=Path, help="JSON file describing Forge work items"
    )
    parser.add_argument("--task", help="Single task summary for one-off runs")
    parser.add_argument(
        "--task-id", default="task-1", help="Identifier for --task mode"
    )
    parser.add_argument("--scope", default="S1", help="Scope tier for --task mode")
    parser.add_argument("--todo", default="T1", help="Todo tier for --task mode")
    parser.add_argument(
        "--target-file",
        action="append",
        default=[],
        help="Target file for --task mode; repeatable",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Constraint for --task mode; repeatable",
    )
    parser.add_argument(
        "--patch-file", type=Path, help="Patch file to evaluate in --task mode"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Path to the ark-core repo root",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after classification and control-field setup",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply accepted deltas back to the repository",
    )
    parser.add_argument(
        "--state-file", type=Path, help="Override the persistent Forge state file path"
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Override the Forge artifact output directory",
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Enable Ollama-backed generation, planning, and redteam",
    )
    parser.add_argument(
        "--ollama-required",
        action="store_true",
        help="Fail task execution when Ollama is unavailable",
    )
    parser.add_argument(
        "--ollama-check",
        action="store_true",
        help="Probe Ollama and print status without running a task",
    )
    parser.add_argument("--ollama-url", help="Override the Ollama /api/generate URL")
    parser.add_argument("--executor-model", help="Override the executor model")
    parser.add_argument("--planner-model", help="Override the planner model")
    parser.add_argument("--redteam-model", help="Override the redteam model")
    parser.add_argument(
        "--ollama-timeout", type=int, help="Timeout in seconds for Ollama calls"
    )
    parser.add_argument(
        "--ollama-num-ctx", type=int, help="Context window for Ollama calls"
    )
    parser.add_argument(
        "--ollama-temperature", type=float, help="Temperature for Ollama calls"
    )
    parser.add_argument("--ollama-top-p", type=float, help="Top-p for Ollama calls")
    parser.add_argument("--ollama-seed", type=int, help="Base seed for Ollama calls")
    parser.add_argument(
        "--ollama-no-planner",
        action="store_true",
        help="Disable planner model calls and use code-built context only",
    )
    parser.add_argument(
        "--ollama-no-redteam",
        action="store_true",
        help="Disable model redteam enrichment and keep heuristic redteam only",
    )
    args = parser.parse_args()
    if args.tasks is None and args.task is None and not args.ollama_check:
        parser.error("provide either --tasks or --task")
    if args.tasks is not None and args.task is not None:
        parser.error("use either --tasks or --task, not both")
    config = _config_from_args(args)
    client = OllamaClient(config=config)
    if args.ollama_check:
        status = client.check(refresh=True)
        print(json.dumps({"ollama": status, "config": client.as_dict()}, indent=2))
        return 0 if (not config.enabled or status["reachable"]) else 1
    orchestrator = ForgeOrchestrator(
        args.repo_root,
        state_path=args.state_file,
        artifacts_dir=args.artifacts_dir,
        apply_accepted=args.apply,
        client=client,
    )
    tasks = _tasks_from_args(args)
    results = [orchestrator.process(task, dry_run=args.dry_run) for task in tasks]
    print(json.dumps(results, indent=2))
    return 0 if all(item["status"] in {"dry_run", "promote"} for item in results) else 1


def _tasks_from_args(args: argparse.Namespace) -> list[ForgeTask]:
    if args.tasks is not None:
        return load_tasks(args.tasks)
    patch = (
        args.patch_file.read_text(encoding="utf-8")
        if args.patch_file is not None
        else None
    )
    return [
        ForgeTask(
            identifier=args.task_id,
            summary=args.task,
            scope=args.scope,
            todo=args.todo,
            target_files=tuple(args.target_file),
            constraints=tuple(args.constraint),
            patch=patch,
        )
    ]


def _config_from_args(args: argparse.Namespace) -> OllamaConfig:
    env_config = OllamaConfig.from_env()
    enabled = env_config.enabled or args.ollama
    required = env_config.required or args.ollama_required
    return OllamaConfig(
        enabled=enabled,
        required=required,
        planner_enabled=not args.ollama_no_planner and env_config.planner_enabled,
        redteam_enabled=not args.ollama_no_redteam and env_config.redteam_enabled,
        base_url=args.ollama_url or env_config.base_url,
        executor_model=args.executor_model or env_config.executor_model,
        planner_model=args.planner_model or env_config.planner_model,
        redteam_model=args.redteam_model or env_config.redteam_model,
        timeout_s=args.ollama_timeout or env_config.timeout_s,
        num_ctx=args.ollama_num_ctx or env_config.num_ctx,
        temperature=args.ollama_temperature
        if args.ollama_temperature is not None
        else env_config.temperature,
        top_p=args.ollama_top_p if args.ollama_top_p is not None else env_config.top_p,
        base_seed=args.ollama_seed
        if args.ollama_seed is not None
        else env_config.base_seed,
    )


def _evaluation_snapshot(evaluation) -> dict[str, object]:
    return {
        "candidate_id": evaluation.candidate_id,
        "detail": evaluation.detail,
        "risk": evaluation.critique.risk,
        "score": evaluation.score,
        "diff_cost": evaluation.diff_cost,
    }


def _verify_snapshot(evaluation) -> dict[str, object]:
    return {
        "tests_ok": evaluation.verify.tests_ok,
        "synth_ok": evaluation.verify.synth_ok,
        "lint_ok": evaluation.verify.lint_ok,
        "types_ok": evaluation.verify.types_ok,
        "coverage_delta": evaluation.verify.coverage_delta,
        "no_new_failures": evaluation.verify.no_new_failures,
        "details": evaluation.verify.details,
    }


def _critique_snapshot(evaluation) -> dict[str, object]:
    return {
        "risk": evaluation.critique.risk,
        "findings": list(evaluation.critique.findings),
        "attackers": dict(evaluation.critique.attackers),
        "counterfactuals": list(evaluation.critique.counterfactuals),
    }


def _emit(
    event_sink: object | None, stage: str, message: str, **fields: object
) -> None:
    if event_sink is None:
        return
    event = {"stage": stage, "message": message}
    event.update(fields)
    event_sink(event)


def _classify_task(
    task: ForgeTask, repo_root: Path, *, python_bin: str
) -> dict[str, object]:
    script = repo_root / "scripts" / "ci" / "enforce_tiers.py"
    rules = repo_root / "config" / "tiering_rules.json"
    payload = [{"id": task.identifier, "scope": task.scope, "todo": task.todo}]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as handle:
        json.dump(payload, handle)
        batch = Path(handle.name)
    try:
        command = [
            python_bin,
            script.as_posix(),
            "--rules",
            rules.as_posix(),
            "--batch",
            batch.as_posix(),
        ]
        return run_command(command, repo_root)
    finally:
        batch.unlink(missing_ok=True)
