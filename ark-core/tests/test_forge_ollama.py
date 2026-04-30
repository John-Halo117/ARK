"""Forge Ollama integration checks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.core.orchestrator import (
    ForgeOrchestrator,
    _config_from_args,
    _tasks_from_args,
)
from forge.context.build import build_context
from forge.memory.ban import BanList
from forge.models.ollama_client import OllamaClient, OllamaConfig, OllamaError
from forge.types import ForgeState, ForgeTask
from forge.verify.redteam import _attack_score, attack_ensemble


def test_ollama_client_extracts_diff_from_chatty_response(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "scripts" / "ai").mkdir(parents=True)
    (tmp_path / "scripts" / "ai" / "worker.py").write_text(
        "value = 1\n", encoding="utf-8"
    )
    task = ForgeTask(
        identifier="ollama-diff",
        summary="update worker value",
        scope="S1",
        todo="T1",
        target_files=("scripts/ai/worker.py",),
    )
    context = build_context(tmp_path, task, BanList(), ForgeState(lkg_id="lkg-1"))
    client = OllamaClient(config=OllamaConfig(enabled=True))

    def fake_call(
        model: str, prompt: str, *, seed: int = 0, format_json: bool = False
    ) -> str:
        assert format_json is False
        return """Here is the patch:
```diff
diff --git a/scripts/ai/worker.py b/scripts/ai/worker.py
--- a/scripts/ai/worker.py
+++ b/scripts/ai/worker.py
@@ -1 +1 @@
-value = 1
+value = 2
```"""

    monkeypatch.setattr(client, "_call", fake_call)

    patch = client.diff(context, seed=3)

    assert patch.startswith("diff --git ")
    assert "value = 2" in patch


def test_attack_ensemble_merges_model_findings() -> None:
    class FakeClient:
        enabled = True

        def critique(self, context, delta: str, mode: str):
            return {
                "risk": "LOW" if mode != "security" else "HIGH",
                "findings": [f"{mode}-finding"],
                "counterfactuals": [f"{mode}-case"],
            }

    task = ForgeTask(identifier="t1", summary="x", scope="S1", todo="T1")
    context = build_context(Path("."), task, BanList(), ForgeState(lkg_id="lkg"))
    candidate = type(
        "Candidate",
        (),
        {
            "patch": "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-x\n+y\n",
            "files_touched": ("a",),
        },
    )()

    critique = attack_ensemble(context, candidate, client=FakeClient())

    assert critique.risk == 0.75
    assert "logic-finding" in critique.findings
    assert "security-finding" in critique.findings
    assert critique.attackers["security"] == 0.75


def test_perf_attack_score_ignores_single_bounded_for_loop() -> None:
    patch = "diff --git a/a.py b/a.py\n+for item in items:\n+    print(item)\n"

    assert _attack_score("perf", patch) == 0.0


def test_perf_attack_score_detects_repeated_for_tokens_and_while_true() -> None:
    nested_patch = (
        "diff --git a/a.py b/a.py\n"
        "+for row in rows:\n"
        "+    for item in row:\n"
        "+        print(item)\n"
    )

    assert _attack_score("perf", nested_patch) == 0.3
    assert _attack_score("perf", "+while true:\n+    pass\n") == 0.3


def test_inline_task_and_ollama_config_from_args(tmp_path: Path) -> None:
    patch_file = tmp_path / "proposal.patch"
    patch_file.write_text(
        "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        tasks=None,
        task="fix inline issue",
        task_id="inline-1",
        scope="S1",
        todo="T1",
        target_file=["a.txt"],
        constraint=["keep interface stable"],
        patch_file=patch_file,
        ollama=True,
        ollama_required=True,
        ollama_url="http://127.0.0.1:11434/api/generate",
        executor_model="exec-model",
        planner_model="plan-model",
        redteam_model="red-model",
        ollama_timeout=30,
        ollama_num_ctx=8192,
        ollama_temperature=0.1,
        ollama_top_p=0.8,
        ollama_seed=11,
        ollama_no_planner=True,
        ollama_no_redteam=True,
    )

    tasks = _tasks_from_args(args)
    config = _config_from_args(args)

    assert tasks[0].patch is not None
    assert tasks[0].target_files == ("a.txt",)
    assert config.enabled is True
    assert config.required is True
    assert config.executor_model == "exec-model"
    assert config.num_ctx == 8192
    assert config.planner_enabled is False
    assert config.redteam_enabled is False


def test_ollama_config_keeps_explicit_zero_numeric_args() -> None:
    args = SimpleNamespace(
        tasks=None,
        task="fix inline issue",
        task_id="inline-1",
        scope="S1",
        todo="T1",
        target_file=[],
        constraint=[],
        patch_file=None,
        ollama=False,
        ollama_required=False,
        ollama_url=None,
        executor_model=None,
        planner_model=None,
        redteam_model=None,
        ollama_timeout=0,
        ollama_num_ctx=0,
        ollama_temperature=None,
        ollama_top_p=None,
        ollama_seed=None,
        ollama_no_planner=False,
        ollama_no_redteam=False,
    )

    config = _config_from_args(args)

    assert config.timeout_s == 0
    assert config.num_ctx == 0


def test_ollama_plan_invalid_json_raises_ollama_error(
    tmp_path: Path, monkeypatch: object
) -> None:
    context = _build_context(tmp_path)
    client = OllamaClient(config=OllamaConfig(enabled=True, planner_enabled=True))
    monkeypatch.setattr(client, "_call", lambda *args, **kwargs: "no json here")

    with pytest.raises(OllamaError, match="invalid JSON"):
        client.plan(context)


def test_ollama_critique_invalid_json_raises_ollama_error(
    tmp_path: Path, monkeypatch: object
) -> None:
    context = _build_context(tmp_path)
    client = OllamaClient(config=OllamaConfig(enabled=True, redteam_enabled=True))
    monkeypatch.setattr(client, "_call", lambda *args, **kwargs: "{bad json")

    with pytest.raises(OllamaError, match="invalid JSON"):
        client.critique(context, "diff --git a/a b/a\n", "security")


def test_invalid_ollama_patch_returns_repair_instead_of_crashing(
    tmp_path: Path,
) -> None:
    repo_root = _build_minimal_repo(tmp_path)
    bad_patch = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -99 +99 @@
-missing
+still missing
"""
    orchestrator = ForgeOrchestrator(
        repo_root,
        apply_accepted=False,
        client=FakeOllamaClient(enabled=True, patch=bad_patch),
    )
    task = ForgeTask(
        identifier="invalid-patch",
        summary="try a broken diff",
        scope="S1",
        todo="T1",
        target_files=("README.md",),
    )

    result = orchestrator.process(task, dry_run=False)

    assert result["status"] == "repair"
    assert "invalid" in result["detail"]


class FakeOllamaClient:
    """Small test double for the Forge orchestrator."""

    def __init__(self, *, enabled: bool, patch: str | None = None) -> None:
        self.enabled = enabled
        self.patch = patch
        self.config = OllamaConfig(enabled=enabled)

    def check(self, *, refresh: bool = False) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "reachable": self.enabled,
            "models": [],
            "error": None,
        }

    def as_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled}

    def require_ready(self) -> dict[str, object]:
        return {"enabled": self.enabled, "reachable": True, "models": [], "error": None}

    def diff(self, context, seed: int = 0):
        return self.patch

    def plan(self, context):
        return None

    def critique(self, context, delta: str, mode: str):
        return None


def _build_minimal_repo(root: Path) -> Path:
    (root / "config").mkdir(parents=True)
    (root / "scripts" / "ci").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "README.md").write_text("Minimal Forge repo\n", encoding="utf-8")
    (root / "tests" / "test_smoke.py").write_text(
        "def test_smoke() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (root / "config" / "tiering_rules.json").write_text(
        json.dumps(
            {
                "scope_tiers": {"S1": 1},
                "todo_tiers": {"T1": 1},
                "manual_review_from": 4,
                "blocked_auto_promote_scopes": [],
                "forbid_mixed_todo_batches": True,
                "reject_mixed_scope_escalation": True,
            }
        ),
        encoding="utf-8",
    )
    (root / "scripts" / "ci" / "enforce_tiers.py").write_text(
        "import json\nprint(json.dumps({'items': [], 'violations': []}))\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    return root


def _build_context(root: Path):
    repo_root = _build_minimal_repo(root)
    task = ForgeTask(
        identifier="ollama-json",
        summary="plan a change",
        scope="S1",
        todo="T1",
        target_files=("README.md",),
    )
    return build_context(repo_root, task, BanList(), ForgeState(lkg_id="lkg"))
