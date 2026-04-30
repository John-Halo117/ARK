"""Forge delta proposal checks."""

from __future__ import annotations

from pathlib import Path

from forge.context.build import build_context
from forge.memory.ban import BanList
from forge.transform.propose import propose_deltas
from forge.types import ForgeState, ForgeTask


def test_task_patch_becomes_candidate(tmp_path: Path) -> None:
    (tmp_path / "scripts" / "ai").mkdir(parents=True)
    (tmp_path / "scripts" / "ai" / "worker.py").write_text(
        "value = 1\n", encoding="utf-8"
    )
    patch = """diff --git a/scripts/ai/worker.py b/scripts/ai/worker.py
--- a/scripts/ai/worker.py
+++ b/scripts/ai/worker.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    task = ForgeTask(
        identifier="patch-task",
        summary="adjust worker value",
        scope="S1",
        todo="T1",
        target_files=("scripts/ai/worker.py",),
        patch=patch,
    )
    state = ForgeState(lkg_id="lkg-1")
    context = build_context(tmp_path, task, BanList(), state)

    candidates = propose_deltas(context, "SIMPLE")

    assert len(candidates) == 1
    assert candidates[0].files_touched == ("scripts/ai/worker.py",)


def test_propose_deltas_skips_invalid_model_patch(tmp_path: Path) -> None:
    (tmp_path / "scripts" / "ai").mkdir(parents=True)
    (tmp_path / "scripts" / "ai" / "worker.py").write_text(
        "value = 1\n", encoding="utf-8"
    )
    task = ForgeTask(
        identifier="proposal-task",
        summary="adjust worker value",
        scope="S1",
        todo="T1",
        target_files=("scripts/ai/worker.py",),
    )
    state = ForgeState(lkg_id="lkg-1")
    context = build_context(tmp_path, task, BanList(), state)

    class FakeClient:
        def diff(self, context, seed: int = 0) -> str:
            if seed == 0:
                return "not a unified diff"
            return """diff --git a/scripts/ai/worker.py b/scripts/ai/worker.py
--- a/scripts/ai/worker.py
+++ b/scripts/ai/worker.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    candidates = propose_deltas(context, "BISECT", client=FakeClient())

    assert len(candidates) == 1
    assert candidates[0].files_touched == ("scripts/ai/worker.py",)
