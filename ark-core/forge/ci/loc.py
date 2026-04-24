"""AST-based Forge structure checks."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..runtime.config import DEFAULT_STRUCTURE_CONFIG, StructurePolicyConfig


@dataclass(frozen=True)
class FunctionSpan:
    """One discovered function span in Forge source."""

    path: str
    qualified_name: str
    start_line: int
    end_line: int
    line_count: int

    @property
    def key(self) -> str:
        return f"{self.path}:{self.qualified_name}"


@dataclass(frozen=True)
class FunctionLengthViolation:
    """One function that exceeded the configured line limit."""

    function: FunctionSpan
    limit: int

    @property
    def excess(self) -> int:
        return self.function.line_count - self.limit


def collect_function_spans(root: Path) -> list[FunctionSpan]:
    """Collect all function and method spans under one Forge root."""

    spans: list[FunctionSpan] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative_path = path.relative_to(root.parent).as_posix()
        spans.extend(_SpanVisitor(relative_path).collect(tree))
    return spans


def find_function_length_violations(
    root: Path,
    *,
    config: StructurePolicyConfig = DEFAULT_STRUCTURE_CONFIG,
) -> list[FunctionLengthViolation]:
    """Return every non-exempt function that exceeds the configured limit."""

    violations: list[FunctionLengthViolation] = []
    for span in collect_function_spans(root):
        if span.line_count <= config.function_line_limit or _is_exempt(span, config):
            continue
        violations.append(
            FunctionLengthViolation(function=span, limit=config.function_line_limit)
        )
    return violations


def format_function_length_violations(violations: list[FunctionLengthViolation]) -> str:
    """Render violations for tests or CLI output."""

    return "\n".join(
        f"{item.function.key} lines={item.function.line_count} limit={item.limit}"
        for item in sorted(
            violations,
            key=lambda value: (value.function.path, value.function.start_line),
        )
    )


class _SpanVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.stack: list[str] = []
        self.spans: list[FunctionSpan] = []

    def collect(self, tree: ast.AST) -> list[FunctionSpan]:
        self.visit(tree)
        return self.spans

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end_line = getattr(node, "end_lineno", node.lineno)
        qualified_name = ".".join([*self.stack, node.name])
        self.spans.append(
            FunctionSpan(
                path=self.relative_path,
                qualified_name=qualified_name,
                start_line=node.lineno,
                end_line=end_line,
                line_count=end_line - node.lineno + 1,
            )
        )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _is_exempt(span: FunctionSpan, config: StructurePolicyConfig) -> bool:
    return span.key in config.function_line_exemptions
