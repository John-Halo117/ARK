"""Forge unified diff application checks."""

from __future__ import annotations

import pytest

from forge.runtime.guards import require_unified_diff
from forge.transform.apply import (
    apply_unified_diff,
    extract_changed_files,
    reverse_unified_diff,
)


def test_apply_unified_diff_rewrites_file(tmp_path) -> None:
    target = tmp_path / "example.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    patch = """diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+delta
 gamma
"""

    apply_unified_diff(tmp_path, patch)

    assert target.read_text(encoding="utf-8") == "alpha\ndelta\ngamma\n"
    assert extract_changed_files(patch) == ("example.txt",)


def test_apply_unified_diff_tolerates_blank_context_without_prefix(tmp_path) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "from sample import run\n\n\ndef demo() -> str:\n    return 'old'\n",
        encoding="utf-8",
    )
    patch = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1,4 +1,4 @@
 from sample import run


 def demo() -> str:
-    return 'old'
+    return 'new'
"""

    apply_unified_diff(tmp_path, patch)

    assert "return 'new'" in target.read_text(encoding="utf-8")


def test_reverse_unified_diff_restores_original_content(tmp_path) -> None:
    target = tmp_path / "example.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    patch = """diff --git a/example.txt b/example.txt
--- a/example.txt
+++ b/example.txt
@@ -1,3 +1,3 @@
 alpha
-beta
+delta
 gamma
"""

    apply_unified_diff(tmp_path, patch)
    apply_unified_diff(tmp_path, reverse_unified_diff(patch))

    assert target.read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


def test_require_unified_diff_rejects_headerless_patch() -> None:
    patch = """--- a/example.txt
+++ b/example.txt
@@ -1 +1 @@
-alpha
+beta
"""

    with pytest.raises(ValueError, match="Forge requires unified diff output only"):
        require_unified_diff(patch)
