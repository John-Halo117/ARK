"""Forge structure-limit checks."""

from __future__ import annotations

from pathlib import Path

from forge.ci.loc import (
    find_function_length_violations,
    format_function_length_violations,
)
from forge.runtime.config import StructurePolicyConfig


def test_function_length_checker_flags_oversized_functions(tmp_path: Path) -> None:
    package_root = tmp_path / "pkg"
    package_root.mkdir()
    module = package_root / "demo.py"
    body = "\n".join(f"    value_{index} = {index}" for index in range(6))
    module.write_text(f"def too_big() -> None:\n{body}\n", encoding="utf-8")

    violations = find_function_length_violations(
        package_root,
        config=StructurePolicyConfig(
            function_line_limit=5, function_line_exemptions=()
        ),
    )

    assert len(violations) == 1
    assert violations[0].function.key == "pkg/demo.py:too_big"
    assert "pkg/demo.py:too_big" in format_function_length_violations(violations)


def test_forge_functions_respect_line_limit() -> None:
    forge_root = Path(__file__).resolve().parents[1] / "forge"

    violations = find_function_length_violations(forge_root)

    assert not violations, format_function_length_violations(violations)
