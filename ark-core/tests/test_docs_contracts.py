"""Canonical doc ownership checks."""

import json
from pathlib import Path

CANONICAL_DOCS = [
    Path("docs") / "ARK_TRUTH_SPINE.md",
    Path("docs") / "CODEX_ARK_SYSTEM_PROMPT.md",
    Path("docs") / "MISSION_GRADE_RULES.md",
    Path("docs") / "SYSTEM_MAP.md",
    Path("docs") / "TODO_TIERS.md",
    Path("docs") / "REDTEAM.md",
]

CANONICAL_CONFIGS = [
    Path("config") / "tiering_rules.json",
    Path("config") / "operating_rules.json",
    Path("config") / "system_invariants.json",
]


def test_canonical_docs_exist(project_root: Path) -> None:
    for rel in CANONICAL_DOCS:
        assert (project_root / rel).is_file(), f"missing canonical doc: {rel}"

    for rel in CANONICAL_CONFIGS:
        assert (project_root / rel).is_file(), f"missing canonical config: {rel}"


def test_readmes_point_to_canonical_docs(project_root: Path) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    foundation = (project_root / "docs" / "ark-field-v4.2-foundation.md").read_text(
        encoding="utf-8"
    )

    for name in [doc.name for doc in CANONICAL_DOCS]:
        assert name in readme, f"{name} missing from README"
        assert name in foundation, f"{name} missing from foundation doc"


def test_mission_grade_rules_reference_machine_files(project_root: Path) -> None:
    mission_rules = (project_root / "docs" / "MISSION_GRADE_RULES.md").read_text(
        encoding="utf-8"
    )

    assert "config/operating_rules.json" in mission_rules
    assert "config/system_invariants.json" in mission_rules


def test_machine_rule_files_have_expected_shape(project_root: Path) -> None:
    operating_rules = json.loads(
        (project_root / "config" / "operating_rules.json").read_text(encoding="utf-8")
    )
    invariants = json.loads(
        (project_root / "config" / "system_invariants.json").read_text(encoding="utf-8")
    )

    assert "control_loop" in operating_rules
    assert "truth_pipeline" in operating_rules
    assert "required_transition_fields" in operating_rules
    assert "required_action_controls" in operating_rules
    assert "invariants" in invariants
    assert invariants["invariants"], "system invariants must not be empty"

    for invariant in invariants["invariants"]:
        assert {"id", "name", "statement", "category"} <= invariant.keys()
