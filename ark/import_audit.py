"""Bounded import registry and self-audit for ARK Python code.

Runtime contract:
- Inputs: ImportAuditConfig with explicit repository root, registry path, scan roots,
  max_files, max_file_bytes, and max_ast_nodes.
- Outputs: ImportAuditReport with structured issue records and library candidates.
- Constraints: scans at most max_files Python files, reads at most max_file_bytes per
  file, and walks at most max_ast_nodes AST nodes per file.
- Failure cases: invalid registry JSON, oversized files, syntax errors, and
  unapproved imports are reported as structured ImportAuditIssue values.
- Determinism: file traversal and output ordering are sorted and independent of
  environment state except the explicit filesystem inputs.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SCAN_ROOTS: tuple[str, ...] = ("ark", "emitters", "agents", "scripts", "tests", "conftest.py")
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "policy" / "import_registry.json"
DEFAULT_MAX_FILES = 512
DEFAULT_MAX_FILE_BYTES = 131_072
DEFAULT_MAX_AST_NODES = 20_000
DEFAULT_MAX_CANDIDATES = 32
DEFAULT_MAX_DIRS = 2_048
DEFAULT_MAX_DIR_ENTRIES = 4_096


@dataclass(frozen=True)
class ImportAuditIssue:
    status: str
    error_code: str
    reason: str
    context: dict[str, Any]
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class LibraryCandidate:
    name: str
    scope: str
    reason: str
    expected_loc_delta: int
    risk: str
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "reason": self.reason,
            "expected_loc_delta": self.expected_loc_delta,
            "risk": self.risk,
            "status": self.status,
        }


@dataclass(frozen=True)
class ImportRegistry:
    version: str
    allowed_roots: frozenset[str]
    stdlib_roots: frozenset[str]
    third_party_roots: frozenset[str]
    internal_roots: frozenset[str]
    library_candidates: tuple[LibraryCandidate, ...] = field(default_factory=tuple)

    def health(self) -> dict[str, Any]:
        return {
            "name": "import_registry",
            "ok": True,
            "version": self.version,
            "allowed_roots": len(self.allowed_roots),
            "library_candidates": len(self.library_candidates),
        }


@dataclass(frozen=True)
class ImportAuditConfig:
    repo_root: Path
    registry_path: Path = DEFAULT_REGISTRY_PATH
    scan_roots: tuple[str, ...] = DEFAULT_SCAN_ROOTS
    max_files: int = DEFAULT_MAX_FILES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_ast_nodes: int = DEFAULT_MAX_AST_NODES
    max_dirs: int = DEFAULT_MAX_DIRS
    max_dir_entries: int = DEFAULT_MAX_DIR_ENTRIES


@dataclass(frozen=True)
class ImportUse:
    file_path: str
    module_root: str
    module_name: str
    line: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "module_root": self.module_root,
            "module_name": self.module_name,
            "line": self.line,
        }


@dataclass(frozen=True)
class ImportAuditReport:
    status: str
    scanned_files: int
    observed_roots: tuple[str, ...]
    issues: tuple[ImportAuditIssue, ...]
    library_candidates: tuple[LibraryCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scanned_files": self.scanned_files,
            "observed_roots": list(self.observed_roots),
            "issues": [issue.as_dict() for issue in self.issues],
            "library_candidates": [candidate.as_dict() for candidate in self.library_candidates],
        }

    def health(self) -> dict[str, Any]:
        return {
            "name": "import_audit",
            "ok": self.status == "ok",
            "scanned_files": self.scanned_files,
            "issues": len(self.issues),
            "observed_roots": len(self.observed_roots),
        }


def load_import_registry(path: Path = DEFAULT_REGISTRY_PATH) -> ImportRegistry:
    raw = _read_text_bounded(path, DEFAULT_MAX_FILE_BYTES)
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_JSON", str(exc), {"path": str(path)})) from exc
    if not isinstance(document, dict):
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_ROOT", "registry root must be an object", {"path": str(path)}))
    version = document.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_VERSION", "registry version must be a string", {"path": str(path)}))
    allowed_roots = frozenset(_read_string_list(document, "allowed_roots", DEFAULT_MAX_AST_NODES))
    stdlib_roots = frozenset(_read_string_list(document, "stdlib_roots", DEFAULT_MAX_AST_NODES))
    third_party_roots = frozenset(_read_string_list(document, "third_party_roots", DEFAULT_MAX_AST_NODES))
    internal_roots = frozenset(_read_string_list(document, "internal_roots", DEFAULT_MAX_AST_NODES))
    candidates = _read_candidates(document.get("library_candidates", []), DEFAULT_MAX_CANDIDATES)
    categorized = stdlib_roots | third_party_roots | internal_roots
    if not categorized.issubset(allowed_roots):
        missing = sorted(categorized - allowed_roots)
        raise ValueError(_failure("IMPORT_REGISTRY_CATEGORY_MISMATCH", "categorized roots must be allowed", {"missing": missing}))
    return ImportRegistry(
        version=version,
        allowed_roots=allowed_roots,
        stdlib_roots=stdlib_roots,
        third_party_roots=third_party_roots,
        internal_roots=internal_roots,
        library_candidates=candidates,
    )


def audit_imports(config: ImportAuditConfig) -> ImportAuditReport:
    registry = load_import_registry(config.registry_path)
    issues: list[ImportAuditIssue] = []
    observed: set[str] = set()
    files = _collect_python_files(config)
    for file_index, path in enumerate(files):
        if file_index >= config.max_files:
            issues.append(_issue("IMPORT_AUDIT_FILE_LIMIT", "file scan limit reached", {"max_files": config.max_files}))
            break
        uses = _extract_imports(path, config.repo_root, config.max_file_bytes, config.max_ast_nodes, issues)
        for use_index, use in enumerate(uses):
            if use_index >= config.max_ast_nodes:
                issues.append(_issue("IMPORT_AUDIT_IMPORT_LIMIT", "import scan limit reached", {"file_path": use.file_path}))
                break
            observed.add(use.module_root)
            if use.module_root not in registry.allowed_roots:
                issues.append(
                    _issue(
                        "IMPORT_ROOT_NOT_REGISTERED",
                        f"import root {use.module_root!r} is not centralized in policy/import_registry.json",
                        use.as_dict(),
                    )
                )
    status = "ok" if not issues else "error"
    return ImportAuditReport(
        status=status,
        scanned_files=len(files),
        observed_roots=tuple(sorted(observed)),
        issues=tuple(issues),
        library_candidates=registry.library_candidates,
    )


def import_audit_health(config: ImportAuditConfig) -> dict[str, Any]:
    return audit_imports(config).health()


def main(argv: tuple[str, ...] | None = None) -> int:
    args = argv if argv is not None else tuple(sys.argv[1:])
    repo_root = Path(args[0]).resolve() if args else Path.cwd().resolve()
    report = audit_imports(ImportAuditConfig(repo_root=repo_root))
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.status == "ok" else 1


def _collect_python_files(config: ImportAuditConfig) -> tuple[Path, ...]:
    files: list[Path] = []
    for root_index, root_name in enumerate(config.scan_roots):
        if root_index >= len(config.scan_roots):
            break
        root = (config.repo_root / root_name).resolve()
        if not _is_relative_to(root, config.repo_root) or not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        if root.is_dir():
            for file_index, path in enumerate(_iter_python_files_bounded(root, config)):
                if file_index >= config.max_files or len(files) >= config.max_files:
                    break
                files.append(path.resolve())
    return tuple(sorted(files)[: config.max_files])


def _iter_python_files_bounded(root: Path, config: ImportAuditConfig) -> tuple[Path, ...]:
    files: list[Path] = []
    dirs: list[Path] = [root]
    visited_dirs = 0
    while dirs and visited_dirs < config.max_dirs and len(files) < config.max_files:
        current = dirs.pop(0)
        visited_dirs += 1
        try:
            entries = sorted(current.iterdir(), key=lambda path: path.name)[: config.max_dir_entries]
        except OSError:
            continue
        for entry_index, entry in enumerate(entries):
            if entry_index >= config.max_dir_entries or len(files) >= config.max_files:
                break
            resolved = entry.resolve()
            if not _is_relative_to(resolved, config.repo_root):
                continue
            if entry.is_dir() and len(dirs) < config.max_dirs:
                dirs.append(resolved)
            elif entry.is_file() and entry.suffix == ".py":
                files.append(resolved)
    return tuple(files)


def _extract_imports(
    path: Path,
    repo_root: Path,
    max_file_bytes: int,
    max_ast_nodes: int,
    issues: list[ImportAuditIssue],
) -> tuple[ImportUse, ...]:
    try:
        source = _read_text_bounded(path, max_file_bytes)
        tree = ast.parse(source, filename=str(path))
    except OSError as exc:
        issues.append(_issue("IMPORT_AUDIT_READ_FAILED", str(exc), {"file_path": str(path)}))
        return ()
    except SyntaxError as exc:
        issues.append(_issue("IMPORT_AUDIT_SYNTAX_ERROR", str(exc), {"file_path": str(path), "line": exc.lineno}))
        return ()
    except ValueError as exc:
        issues.append(_issue("IMPORT_AUDIT_FILE_TOO_LARGE", str(exc), {"file_path": str(path)}))
        return ()
    imports: list[ImportUse] = []
    for node_index, node in enumerate(ast.walk(tree)):
        if node_index >= max_ast_nodes:
            issues.append(_issue("IMPORT_AUDIT_AST_LIMIT", "AST node limit reached", {"file_path": str(path)}))
            break
        if isinstance(node, ast.Import):
            for alias_index, alias in enumerate(node.names):
                if alias_index >= max_ast_nodes:
                    break
                imports.append(_import_use(path, repo_root, alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(_import_use(path, repo_root, node.module, node.lineno))
    return tuple(imports)


def _import_use(path: Path, repo_root: Path, module_name: str, line: int) -> ImportUse:
    root = module_name.split(".", 1)[0]
    try:
        file_path = str(path.relative_to(repo_root))
    except ValueError:
        file_path = str(path)
    return ImportUse(file_path=file_path, module_root=root, module_name=module_name, line=line)


def _read_text_bounded(path: Path, max_bytes: int) -> str:
    encoded = path.read_bytes()
    if len(encoded) > max_bytes:
        raise ValueError(f"{path} exceeds {max_bytes} bytes")
    return encoded.decode("utf-8")


def _read_string_list(document: dict[str, Any], key: str, max_items: int) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list):
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_LIST", f"{key} must be a list", {"field": key}))
    result: list[str] = []
    for index, item in enumerate(value):
        if index >= max_items:
            raise ValueError(_failure("IMPORT_REGISTRY_LIST_TOO_LONG", f"{key} exceeds max items", {"field": key}))
        if not isinstance(item, str) or not item:
            raise ValueError(_failure("IMPORT_REGISTRY_INVALID_ITEM", f"{key} must contain strings", {"field": key}))
        result.append(item)
    return tuple(result)


def _read_candidates(value: Any, max_items: int) -> tuple[LibraryCandidate, ...]:
    if not isinstance(value, list):
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_CANDIDATES", "library_candidates must be a list", {}))
    candidates: list[LibraryCandidate] = []
    for index, item in enumerate(value):
        if index >= max_items:
            raise ValueError(_failure("IMPORT_REGISTRY_TOO_MANY_CANDIDATES", "library candidate limit exceeded", {}))
        if not isinstance(item, dict):
            raise ValueError(_failure("IMPORT_REGISTRY_INVALID_CANDIDATE", "library candidate must be an object", {"index": index}))
        candidates.append(
            LibraryCandidate(
                name=_required_str(item, "name", index),
                scope=_required_str(item, "scope", index),
                reason=_required_str(item, "reason", index),
                expected_loc_delta=_required_int(item, "expected_loc_delta", index),
                risk=_required_str(item, "risk", index),
                status=_required_str(item, "status", index),
            )
        )
    return tuple(candidates)


def _required_str(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_CANDIDATE_FIELD", f"{key} must be a string", {"index": index}))
    return value


def _required_int(item: dict[str, Any], key: str, index: int) -> int:
    value = item.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(_failure("IMPORT_REGISTRY_INVALID_CANDIDATE_FIELD", f"{key} must be an integer", {"index": index}))
    return value


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _issue(error_code: str, reason: str, context: dict[str, Any], recoverable: bool = True) -> ImportAuditIssue:
    return ImportAuditIssue(
        status="error",
        error_code=error_code,
        reason=reason,
        context=context,
        recoverable=recoverable,
    )


def _failure(error_code: str, reason: str, context: dict[str, Any], recoverable: bool = True) -> str:
    return json.dumps(
        {
            "status": "error",
            "error_code": error_code,
            "reason": reason,
            "context": context,
            "recoverable": recoverable,
        },
        sort_keys=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
