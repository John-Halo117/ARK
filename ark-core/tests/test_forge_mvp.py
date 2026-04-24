"""Forge MVP integration checks."""

from __future__ import annotations

import json
from pathlib import Path

from forge.context.build import build_context
from forge.core.orchestrator import ForgeOrchestrator
from forge.models.ollama_client import OllamaConfig
from forge.types import ForgeTask
from forge.verify.adapters import VerificationRun


def test_orchestrator_applies_accepted_patch_and_persists_state(tmp_path: Path) -> None:
    repo_root = _build_minimal_repo(tmp_path)
    orchestrator = ForgeOrchestrator(
        repo_root,
        apply_accepted=True,
        client=FakeOllamaClient(enabled=False),
    )
    patch = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 Minimal Forge repo
+MVP applied
"""
    task = ForgeTask(
        identifier="mvp-apply",
        summary="append proof line to readme",
        scope="S1",
        todo="T1",
        target_files=("README.md",),
        patch=patch,
    )

    result = orchestrator.process(task, dry_run=False)

    assert result["status"] == "promote"
    assert result["applied"] is True
    assert "MVP applied" in (repo_root / "README.md").read_text(encoding="utf-8")
    assert Path(result["artifacts"]["result"]).exists()
    assert Path(result["artifacts"]["accepted_patch"]).exists()

    state_payload = json.loads(
        (repo_root / ".forge" / "state.json").read_text(encoding="utf-8")
    )
    assert state_payload["state"]["attempt"] == 1

    reloaded = ForgeOrchestrator(repo_root, apply_accepted=False)
    assert reloaded.state.lkg_id == result["lkg_id"]
    assert reloaded.state.attempt == 1


def test_orchestrator_uses_injected_context_provider_and_verifier(
    tmp_path: Path,
) -> None:
    repo_root = _build_minimal_repo(tmp_path)
    provider = FakeContextProvider()
    verifier = FakeVerifier()
    patch = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 Minimal Forge repo
+Injected provider path
"""
    task = ForgeTask(
        identifier="mvp-extensible",
        summary="append injected line to readme",
        scope="S1",
        todo="T1",
        target_files=("README.md",),
        patch=patch,
    )
    orchestrator = ForgeOrchestrator(
        repo_root,
        apply_accepted=False,
        client=FakeOllamaClient(enabled=False),
        context_provider=provider,
        verifier=verifier,
    )

    result = orchestrator.process(task, dry_run=False)

    assert result["status"] == "promote"
    assert provider.build_calls == 1
    assert verifier.run_calls == 1


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


class FakeContextProvider:
    def __init__(self) -> None:
        self.build_calls = 0

    def build(self, repo_root: Path, task: ForgeTask, banlist, state):
        self.build_calls += 1
        return build_context(repo_root, task, banlist, state)

    def enrich_with_plan(self, context, plan):
        return context


class FakeVerifier:
    def __init__(self) -> None:
        self.run_calls = 0

    def baseline_coverage(
        self, repo_root: Path, *, tool_root: Path | None = None
    ) -> float:
        return 100.0

    def run(
        self,
        context,
        sandbox_root: Path,
        *,
        tool_root: Path,
        baseline_coverage: float | None = None,
    ) -> VerificationRun:
        self.run_calls += 1
        return VerificationRun(
            tests={"ok": True, "coverage": 100.0},
            lint={"ok": True},
            types={"ok": True},
            gate={"ok": True},
            baseline_coverage=100.0,
        )


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
        """
import json

print(json.dumps({"items": [], "violations": []}))
raise SystemExit(0)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return root
