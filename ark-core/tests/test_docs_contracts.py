"""Canonical doc ownership checks."""

from pathlib import Path

CANONICAL_DOCS = [
    Path("docs") / "ARK_TRUTH_SPINE.md",
    Path("docs") / "CODEX_ARK_SYSTEM_PROMPT.md",
    Path("docs") / "SYSTEM_MAP.md",
    Path("docs") / "TODO_TIERS.md",
    Path("docs") / "REDTEAM.md",
]


def test_canonical_docs_exist(project_root: Path) -> None:
    for rel in CANONICAL_DOCS:
        assert (project_root / rel).is_file(), f"missing canonical doc: {rel}"


def test_readmes_point_to_canonical_docs(project_root: Path) -> None:
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    foundation = (project_root / "docs" / "ark-field-v4.2-foundation.md").read_text(
        encoding="utf-8"
    )

    for name in [doc.name for doc in CANONICAL_DOCS]:
        assert name in readme, f"{name} missing from README"
        assert name in foundation, f"{name} missing from foundation doc"
