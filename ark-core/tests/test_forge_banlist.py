"""Forge failure-memory checks."""

from __future__ import annotations

from forge.memory.ban import BanList, failure_record


def test_banlist_blocks_repeats_then_decays() -> None:
    patch = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    record = failure_record(patch, "executor", "candidate_failure")
    banlist = BanList()
    banlist.add(record, step=0)

    assert banlist.is_blocked(record, step=0)
    assert banlist.is_blocked(record, step=2)
    assert not banlist.is_blocked(record, step=20)
