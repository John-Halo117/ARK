"""Forge browser app checks."""

from __future__ import annotations

from pathlib import Path

from forge.ui import browser
from forge.ui.common import PATCH_APPLY_ERROR, PATCH_REVERT_ERROR


def test_browser_snapshot_exposes_quickstart_and_legend(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser.BrowserState(tmp_path)
    snapshot = state.snapshot()

    assert "Forge browser app ready" in snapshot["logs"][-1]
    assert snapshot["legend"][0]["command"] == "Start"
    assert "plain English" in snapshot["quickstart"][0]
    assert snapshot["example_tasks"]
    assert snapshot["workflow_presets"]
    assert snapshot["tool_profiles"]
    assert snapshot["capabilities"]
    assert snapshot["runtime"]["ready"] is True
    assert "qwen3-coder:30b" in snapshot["runtime_summary"]


def test_browser_mode_and_tau_commands_update_state(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser.BrowserState(Path(tmp_path))
    state.handle_command({"command": "mode tri"})
    state.handle_command({"command": "tau 0.25"})

    snapshot = state.snapshot()

    assert snapshot["controls"]["mode_override"] == "TRISECT"
    assert snapshot["controls"]["risk_threshold"] == 0.25


def test_browser_expand_and_test_mode_commands_update_state(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser.BrowserState(Path(tmp_path))
    state.handle_command({"command": "expand"})
    state.handle_command({"command": "tests fast"})

    snapshot = state.snapshot()

    assert snapshot["controls"]["context_level"] == 1
    assert snapshot["controls"]["test_mode"] == "fast"


def test_browser_tool_profile_updates_controls(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser.BrowserState(Path(tmp_path))
    result = state.handle_action({"action": "set_tool_profile", "id": "devin"})
    snapshot = state.snapshot()

    assert result["ok"] is True
    assert snapshot["controls"]["tool_profile"] == "devin"
    assert snapshot["controls"]["mode_override"] == "TRISECT"
    assert snapshot["controls"]["planner"] is True


def test_browser_safe_revert_undoes_latest_applied_patch(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    target = tmp_path / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    state = browser.BrowserState(Path(tmp_path))
    browser.apply_unified_diff(tmp_path, patch)
    state._remember_applied_patch(
        label="live candidate delta-1",
        patch=patch,
        files_touched=("app.py",),
        source="browser_accept",
        task="raise value",
        identifier="delta-1",
    )

    result = state.apply_safe_revert()

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_browser_accept_selected_patch_hides_patch_error_details(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser._LegacyBrowserState(Path(tmp_path))
    state.selected_candidate_id = "delta-1"
    state.live_candidates["delta-1"] = browser.CandidateRecord(
        identifier="delta-1",
        patch="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
        files_touched=("app.py",),
    )

    result = state.accept_selected_patch()

    assert result == {"ok": False, "error": PATCH_APPLY_ERROR}


def test_browser_apply_safe_revert_hides_patch_error_details(
    monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        browser,
        "detect_ollama_endpoint",
        lambda preferred_url=None, timeout_s=5: (
            "http://127.0.0.1:11434/api/generate",
            ["qwen3-coder:30b"],
        ),
    )
    monkeypatch.setattr(
        browser, "choose_model", lambda models, preferred=None: "qwen3-coder:30b"
    )
    monkeypatch.setattr(browser, "load_history_records", lambda artifacts_dir: [])

    state = browser._LegacyBrowserState(Path(tmp_path))
    state.applied_history.append(
        browser.AppliedDeltaRecord(
            identifier="delta-1",
            label="live candidate delta-1",
            patch_text="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
            revert_patch="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-new\n+old\n",
            files_touched=("app.py",),
            source="browser_accept",
            task="fix app",
            patch_path=None,
        )
    )

    result = state.apply_safe_revert()

    assert result == {"ok": False, "error": PATCH_REVERT_ERROR}
