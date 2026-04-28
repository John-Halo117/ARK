from __future__ import annotations

import json
from pathlib import Path

from ark.import_audit import ImportAuditConfig, audit_imports, load_import_registry


def test_import_registry_loads_current_manifest():
    registry = load_import_registry()

    assert "ark" in registry.allowed_roots
    assert "aiohttp" in registry.third_party_roots
    assert registry.health()["ok"] is True
    assert registry.library_candidates


def test_import_audit_passes_current_repo():
    report = audit_imports(ImportAuditConfig(repo_root=Path.cwd()))

    assert report.status == "ok"
    assert "ark" in report.observed_roots
    assert report.health()["ok"] is True


def test_import_audit_detects_unregistered_import(tmp_path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": "test",
                "allowed_roots": ["json"],
                "stdlib_roots": ["json"],
                "third_party_roots": [],
                "internal_roots": [],
                "library_candidates": [],
            }
        ),
        encoding="utf-8",
    )
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text("import requests\nimport json\n", encoding="utf-8")

    report = audit_imports(
        ImportAuditConfig(
            repo_root=tmp_path,
            registry_path=registry_path,
            scan_roots=("pkg",),
            max_files=8,
            max_file_bytes=4096,
            max_ast_nodes=128,
        )
    )

    assert report.status == "error"
    assert report.issues[0].error_code == "IMPORT_ROOT_NOT_REGISTERED"
    assert report.issues[0].context["module_root"] == "requests"
