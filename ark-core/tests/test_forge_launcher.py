"""Low-friction Forge launcher checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from forge.models.discovery import choose_model
from forge.ui import launcher


def test_choose_model_prefers_coder_family() -> None:
    models = ["llama3:8b", "qwen3-coder:30b", "codellama:7b"]

    chosen = choose_model(models)

    assert chosen == "qwen3-coder:30b"


def test_launcher_uses_auto_defaults(
    monkeypatch: object, tmp_path: Path, capsys
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(
            self, repo_root: Path, *, apply_accepted: bool, client: object
        ) -> None:
            captured["repo_root"] = repo_root
            captured["apply_accepted"] = apply_accepted
            captured["client"] = client

        def process(self, task, *, dry_run: bool):
            captured["task"] = task
            captured["dry_run"] = dry_run
            return {
                "status": "promote",
                "detail": "all gates passed",
                "phi": 0.72,
                "mode": "BISECT",
                "applied": True,
                "artifacts": {"result": str(tmp_path / "result.json")},
            }

    monkeypatch.setattr(
        launcher,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://172.21.32.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(launcher, "ForgeOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        launcher,
        "OllamaClient",
        lambda config: type("FakeClient", (), {"config": config})(),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "forge.py",
            "fix the greeting bug",
            "greetings.py",
            "tests/test_greetings.py",
            "--repo-root",
            str(tmp_path),
        ],
    )

    code = launcher.main()
    output = capsys.readouterr().out

    assert code == 0
    assert "Forge status: promote" in output
    assert captured["apply_accepted"] is True
    assert captured["dry_run"] is False
    assert captured["task"].target_files == ("greetings.py", "tests/test_greetings.py")
    assert captured["client"].config.planner_enabled is False
    assert captured["client"].config.redteam_enabled is False


def test_launcher_defaults_to_tui(monkeypatch: object, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(launcher, "_ui_available", lambda: True)
    monkeypatch.setattr(launcher.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        launcher,
        "_launch_ui",
        lambda args, repo_root: captured.update({"repo_root": repo_root}) or 0,
    )
    monkeypatch.setattr("sys.argv", ["forge.py", "--repo-root", str(tmp_path)])

    code = launcher.main()

    assert code == 0
    assert captured["repo_root"] == tmp_path


def test_launcher_explicit_desktop(monkeypatch: object, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        launcher,
        "_launch_desktop",
        lambda args, repo_root: (
            captured.update({"repo_root": repo_root, "port": args.desktop_port}) or 0
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "forge.py",
            "--desktop",
            "--desktop-port",
            "4899",
            "--repo-root",
            str(tmp_path),
        ],
    )

    code = launcher.main()

    assert code == 0
    assert captured["repo_root"] == tmp_path
    assert captured["port"] == 4899


def test_launcher_interactive_mode_guides_user(
    monkeypatch: object, tmp_path: Path, capsys
) -> None:
    captured: dict[str, object] = {}
    prompts = iter(
        [
            "fix the greeting bug",
            "greetings.py tests/test_greetings.py",
            "keep the public function name stable",
            "n",
            "y",
        ]
    )

    class FakeOrchestrator:
        def __init__(
            self, repo_root: Path, *, apply_accepted: bool, client: object
        ) -> None:
            captured["repo_root"] = repo_root
            captured["apply_accepted"] = apply_accepted
            captured["client"] = client

        def process(self, task, *, dry_run: bool):
            captured["task"] = task
            captured["dry_run"] = dry_run
            return {
                "status": "promote",
                "detail": "all gates passed",
                "phi": 0.81,
                "mode": "SIMPLE",
                "applied": True,
                "artifacts": {"result": str(tmp_path / "result.json")},
            }

    monkeypatch.setattr(
        launcher,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://172.21.32.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(launcher, "ForgeOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        launcher,
        "OllamaClient",
        lambda config: type("FakeClient", (), {"config": config})(),
    )
    monkeypatch.setattr(launcher, "_ui_available", lambda: False)
    monkeypatch.setattr(launcher, "_prompt", lambda label: next(prompts))
    monkeypatch.setattr(launcher.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        "sys.argv", ["forge.py", "--no-ui", "--repo-root", str(tmp_path)]
    )

    code = launcher.main()
    output = capsys.readouterr().out

    assert code == 0
    assert "Forge interactive mode" in output
    assert captured["apply_accepted"] is True
    assert captured["dry_run"] is False
    assert captured["task"].summary == "fix the greeting bug"
    assert captured["task"].target_files == ("greetings.py", "tests/test_greetings.py")
    assert captured["task"].constraints == ("keep the public function name stable",)


def test_launcher_check_mode_reports_runtime(monkeypatch: object, capsys) -> None:
    monkeypatch.setattr(
        launcher,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://172.21.32.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        launcher,
        "_prompt",
        lambda label: (_ for _ in ()).throw(
            AssertionError("check mode should not prompt")
        ),
    )
    monkeypatch.setattr("sys.argv", ["forge.py", "--check"])

    code = launcher.main()
    output = capsys.readouterr().out

    assert code == 0
    assert "Forge runtime:" in output
    assert "qwen3-coder:30b" in output
    assert "forge>" not in output


def test_launcher_without_tty_prints_start_here(
    monkeypatch: object, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(
        launcher,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://172.21.32.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(launcher.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr("sys.argv", ["forge.py", "--repo-root", str(tmp_path)])

    code = launcher.main()
    output = capsys.readouterr().out

    assert code == 1
    assert "Forge start here" in output
    assert "./forge" in output


def test_windows_launchers_resolve_real_python(project_root: Path) -> None:
    repo_root = project_root.parent
    cmd_text = (repo_root / "forge.cmd").read_text(encoding="utf-8")
    ps1_text = (repo_root / "forge.ps1").read_text(encoding="utf-8")

    assert 'set "PYTHON_BIN=py"' not in cmd_text
    assert '$PythonBin = "py"' not in ps1_text
    assert "print(sys.executable)" in cmd_text
    assert "print(sys.executable)" in ps1_text
