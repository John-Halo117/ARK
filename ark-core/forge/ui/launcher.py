"""Low-friction Forge launcher."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from ..core.orchestrator import ForgeOrchestrator
from ..models.discovery import (
    compact_runtime_summary,
    detect_ollama_endpoint,
    choose_model,
)
from ..models.ollama_client import OllamaClient, OllamaConfig
from ..runtime.config import DEFAULT_UI_STATE_CONFIG
from ..types import ForgeTask


def main() -> int:
    """Launch Forge with Codex-like defaults."""

    parser = _build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    if args.desktop:
        return _launch_desktop(args, repo_root)

    if _should_launch_ui(args):
        return _launch_ui(args, repo_root)

    endpoint, model, models, summary = _detect_runtime(args)

    if args.examples:
        print(_render_examples(repo_root))
        return 0
    if args.check or args.doctor:
        return _handle_check_mode(args, repo_root, endpoint, model, models, summary)

    task_text, target_files, constraints, dry_run, apply_accepted = (
        _resolve_task_request(
            parser,
            args,
            repo_root,
            endpoint,
            model,
            summary,
        )
    )
    if task_text is None:
        return 1

    client = OllamaClient(config=_build_ollama_config(args, endpoint, model))
    orchestrator = ForgeOrchestrator(
        repo_root, apply_accepted=apply_accepted, client=client
    )
    task = ForgeTask(
        identifier="forge-task-1",
        summary=task_text,
        scope=args.scope,
        todo=args.todo,
        target_files=tuple(target_files),
        constraints=tuple(constraints),
    )
    result = orchestrator.process(task, dry_run=dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in {"dry_run", "promote"} else 1

    print(_render_summary(repo_root, summary, result))
    return 0 if result["status"] in {"dry_run", "promote"} else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", help="Natural language task for Forge")
    parser.add_argument("files", nargs="*", help="Target files to constrain the task")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository to modify; defaults to the current directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate readiness without applying the accepted delta",
    )
    parser.add_argument(
        "--no-apply",
        action="store_true",
        help="Do not write the accepted delta back to the repo",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Show the auto-detected Ollama runtime and exit",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Human-friendly runtime check with next steps",
    )
    parser.add_argument(
        "--examples", action="store_true", help="Show copy-paste examples and exit"
    )
    parser.add_argument(
        "--desktop", action="store_true", help="Open the browser-based Forge app"
    )
    parser.add_argument(
        "--desktop-port",
        type=int,
        default=DEFAULT_UI_STATE_CONFIG.default_browser_port,
        help="Port for the browser-based Forge app",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser tab for the browser app",
    )
    parser.add_argument(
        "--ui", action="store_true", help="Open the Forge control-panel TUI"
    )
    parser.add_argument(
        "--no-ui", action="store_true", help="Skip the TUI and stay in CLI mode"
    )
    parser.add_argument("--model", help="Override the auto-selected executor model")
    parser.add_argument("--ollama-url", help="Override the auto-detected Ollama URL")
    parser.add_argument(
        "--timeout", type=int, default=300, help="Ollama timeout in seconds"
    )
    parser.add_argument(
        "--num-ctx", type=int, default=2048, help="Context window passed to Ollama"
    )
    parser.add_argument(
        "--full-model-loop",
        action="store_true",
        help="Use Ollama for planner and redteam too; slower but fuller",
    )
    parser.add_argument("--scope", default="S1", help="Scope tier for the task")
    parser.add_argument("--todo", default="T1", help="Todo tier for the task")
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Constraint for the task; repeatable",
    )
    parser.add_argument("--json", action="store_true", help="Emit raw JSON only")
    return parser


def _detect_runtime(
    args: argparse.Namespace,
) -> tuple[str | None, str | None, list[str], str]:
    endpoint, models = detect_ollama_endpoint(
        preferred_url=args.ollama_url, timeout_s=5
    )
    model = choose_model(models, preferred=args.model)
    summary = compact_runtime_summary(endpoint, model, models)
    return endpoint, model, models, summary


def _handle_check_mode(
    args: argparse.Namespace,
    repo_root: Path,
    endpoint: str | None,
    model: str | None,
    models: list[str],
    summary: str,
) -> int:
    payload = {
        "ollama_url": endpoint,
        "model": model,
        "models": models,
        "summary": summary,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_render_check_summary(repo_root, summary, endpoint, model, models))
    return 0 if endpoint is not None else 1


def _should_launch_ui(args: argparse.Namespace) -> bool:
    if args.no_ui:
        return False
    if args.ui:
        return True
    if args.task is not None or args.check or args.doctor or args.examples or args.json:
        return False
    return sys.stdin.isatty() and _ui_available()


def _ui_available() -> bool:
    return importlib.util.find_spec("textual") is not None


def _launch_ui(args: argparse.Namespace, repo_root: Path) -> int:
    from .app import launch

    return launch(
        repo_root,
        preferred_model=args.model,
        preferred_url=args.ollama_url,
        timeout_s=args.timeout,
        num_ctx=args.num_ctx,
    )


def _launch_desktop(args: argparse.Namespace, repo_root: Path) -> int:
    from .browser import launch

    return launch(
        repo_root,
        preferred_model=args.model,
        preferred_url=args.ollama_url,
        timeout_s=args.timeout,
        num_ctx=args.num_ctx,
        port=args.desktop_port,
        open_browser=not args.no_browser,
    )


def _resolve_task_request(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repo_root: Path,
    endpoint: str | None,
    model: str | None,
    summary: str,
) -> tuple[str | None, list[str], list[str], bool, bool]:
    if args.task:
        return (
            args.task,
            list(args.files),
            list(args.constraint),
            args.dry_run,
            not args.no_apply,
        )

    if not sys.stdin.isatty():
        print(_render_start_here(repo_root, summary))
        return None, [], [], True, False

    return _interactive_request(parser, args, repo_root, endpoint, model, summary)


def _interactive_request(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repo_root: Path,
    endpoint: str | None,
    model: str | None,
    summary: str,
) -> tuple[str, list[str], list[str], bool, bool]:
    print(_render_welcome(repo_root, summary))
    if endpoint is None or model is None:
        print(_render_runtime_bootstrap())
        raise SystemExit(1)

    task_text = _prompt_until_nonempty("What do you want Forge to do?\nforge> ")
    if not task_text:
        parser.error("provide a task, run `./forge`, or use --check")
    files = _split_words(
        _prompt(
            "Files to focus on (optional, space-separated; press Enter to let Forge decide): "
        )
    )
    constraint = _prompt("Anything Forge must preserve? (optional): ")
    dry_run = _prompt_yes_no("Preview only first? [y/N]: ", default=False)
    apply_accepted = (
        False
        if dry_run
        else _prompt_yes_no(
            "Apply accepted changes automatically? [Y/n]: ",
            default=True,
        )
    )
    constraints = [constraint] if constraint else list(args.constraint)
    return task_text, files, constraints, dry_run, apply_accepted


def _build_ollama_config(
    args: argparse.Namespace,
    endpoint: str | None,
    model: str | None,
) -> OllamaConfig:
    if endpoint is None or model is None:
        raise SystemExit(
            "Forge could not auto-detect a usable Ollama runtime. "
            "Run `./forge --check` for details."
        )
    return OllamaConfig(
        enabled=True,
        required=True,
        planner_enabled=args.full_model_loop,
        redteam_enabled=args.full_model_loop,
        base_url=endpoint,
        executor_model=model,
        planner_model=model,
        redteam_model=model,
        timeout_s=args.timeout,
        num_ctx=args.num_ctx,
        temperature=0.2,
        top_p=0.9,
        base_seed=0,
    )


def _prompt(label: str) -> str:
    try:
        return input(label).strip()
    except EOFError:
        return ""


def _prompt_until_nonempty(label: str) -> str:
    while True:
        value = _prompt(label)
        if value:
            return value
        print("Please type a short task, like: fix the failing tests")


def _prompt_yes_no(label: str, *, default: bool) -> bool:
    while True:
        value = _prompt(label).lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _split_words(value: str) -> list[str]:
    return [item for item in value.split() if item]


def _render_summary(
    repo_root: Path, runtime_summary: str, result: dict[str, object]
) -> str:
    lines = [
        f"Forge repo: {repo_root}",
        f"Forge runtime: {runtime_summary}",
        f"Forge status: {result['status']}",
        f"Detail: {result['detail']}",
        f"Phi: {result['phi']:.3f} | Mode: {result['mode']} | Applied: {result['applied']}",
    ]
    artifacts = result.get("artifacts", {})
    if artifacts:
        lines.append(
            f"Artifacts: {', '.join(str(value) for value in artifacts.values())}"
        )
    return "\n".join(lines)


def _render_check_summary(
    repo_root: Path,
    runtime_summary: str,
    endpoint: str | None,
    model: str | None,
    models: list[str],
) -> str:
    lines = [
        f"Forge repo default: {repo_root}",
        f"Forge runtime: {runtime_summary}",
    ]
    if models:
        lines.append(f"Installed models: {', '.join(models)}")
    if endpoint is None:
        lines.append(
            "Next step: start Ollama or pass --ollama-url to point Forge at a running instance."
        )
    elif model is None:
        lines.append(
            "Next step: pull a coder model or pass --model to choose one explicitly."
        )
    else:
        lines.append("Fastest start: run `./forge` to open the Forge control panel.")
        lines.append("Browser app: `./forge --desktop`")
        lines.append(
            'One-liner: ./forge "fix the failing test" path/to/file.py tests/test_file.py'
        )
        lines.append('Dry run: ./forge --dry-run "describe the change"')
    return "\n".join(lines)


def _render_welcome(repo_root: Path, runtime_summary: str) -> str:
    return "\n".join(
        [
            "Forge interactive mode",
            f"Repo: {repo_root}",
            f"Runtime: {runtime_summary}",
            "Just answer the prompts. Press Ctrl+C any time to stop.",
        ]
    )


def _render_runtime_bootstrap() -> str:
    return "\n".join(
        [
            "Forge could not find a ready Ollama runtime.",
            "Try this first:",
            "  1. Start Ollama: `ollama serve`",
            "  2. Pull a coder model: `ollama pull qwen3-coder:30b`",
            "  3. Re-run: `./forge --check`",
            "If Ollama is running somewhere else, pass `--ollama-url`.",
        ]
    )


def _render_start_here(repo_root: Path, runtime_summary: str) -> str:
    return "\n".join(
        [
            "Forge start here",
            f"Repo: {repo_root}",
            f"Runtime: {runtime_summary}",
            "Run one of these from the ARK repo root:",
            "  ./forge",
            "  ./forge --desktop",
            "  ./forge --ui",
            "  ./forge --check",
            '  ./forge "fix the failing test" path/to/file.py tests/test_file.py',
            "Windows PowerShell: .\\forge.ps1",
            "Windows Command Prompt: forge.cmd",
        ]
    )


def _render_examples(repo_root: Path) -> str:
    return "\n".join(
        [
            "Forge examples",
            f"Repo default: {repo_root}",
            "Control panel: ./forge",
            "Browser app: ./forge --desktop",
            "Runtime check: ./forge --check",
            'Fix a bug: ./forge "fix the failing login test" app/auth.py tests/test_auth.py',
            'Preview only: ./forge --dry-run "refactor the parser without changing behavior" parser.py',
            "Force CLI mode: ./forge --no-ui",
            'Full model loop: ./forge --full-model-loop "harden the retry logic" service/retry.py',
        ]
    )
