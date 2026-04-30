"""Unified diff parsing and application for Forge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[Hunk, ...]


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def extract_changed_files(patch: str) -> tuple[str, ...]:
    """Return the deduplicated set of files touched by a unified diff."""

    files: list[str] = []
    for file_patch in parse_patch(patch):
        path = file_patch.new_path or file_patch.old_path
        if path is not None and path not in files:
            files.append(path)
    return tuple(files)


def extract_hunk_headers(patch: str) -> tuple[str, ...]:
    """Return stable hunk fingerprints for failure memory."""

    return tuple(line.strip() for line in patch.splitlines() if line.startswith("@@"))


def reverse_unified_diff(patch: str) -> str:
    """Return a reversible diff that undoes the supplied patch."""

    lines: list[str] = []
    for file_patch in parse_patch(patch):
        label = file_patch.new_path or file_patch.old_path or "unknown"
        old_header = file_patch.new_path
        new_header = file_patch.old_path
        lines.append(f"diff --git a/{label} b/{label}")
        lines.append(f"--- {_header_path(old_header, 'a')}")
        lines.append(f"+++ {_header_path(new_header, 'b')}")
        for hunk in file_patch.hunks:
            lines.append(
                "@@ "
                f"-{hunk.new_start},{hunk.new_count} "
                f"+{hunk.old_start},{hunk.old_count} "
                "@@"
            )
            lines.extend(_reverse_hunk_lines(hunk.lines))
    return "\n".join(lines) + ("\n" if lines else "")


def parse_patch(patch: str) -> tuple[FilePatch, ...]:
    """Parse a unified diff into file-level patches."""

    lines = patch.splitlines()
    files: list[FilePatch] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("diff --git "):
            index += 1
            continue
        old_path, new_path, index = _parse_headers(lines, index + 1)
        hunks, index = _parse_hunks(lines, index)
        files.append(
            FilePatch(old_path=old_path, new_path=new_path, hunks=tuple(hunks))
        )
    return tuple(files)


def apply_unified_diff(root: Path, patch: str) -> None:
    """Apply a unified diff to a filesystem tree."""

    for file_patch in parse_patch(patch):
        _apply_file_patch(root, file_patch)


def _parse_headers(lines: list[str], index: int) -> tuple[str | None, str | None, int]:
    old_path = None
    new_path = None
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            old_path = _normalize_path(line[4:])
        elif line.startswith("+++ "):
            new_path = _normalize_path(line[4:])
            index += 1
            break
        index += 1
    return old_path, new_path, index


def _normalize_path(raw: str) -> str | None:
    if raw == "/dev/null":
        return None
    if raw.startswith("a/") or raw.startswith("b/"):
        return raw[2:]
    return raw


def _header_path(path: str | None, prefix: str) -> str:
    if path is None:
        return "/dev/null"
    return f"{prefix}/{path}"


def _reverse_hunk_lines(lines: tuple[str, ...]) -> list[str]:
    reversed_lines: list[str] = []
    for line in lines:
        prefix, text = line[:1], line[1:]
        if prefix == "+":
            reversed_lines.append(f"-{text}")
        elif prefix == "-":
            reversed_lines.append(f"+{text}")
        else:
            reversed_lines.append(line)
    return reversed_lines


def _normalize_hunk_line(line: str) -> str:
    """Tolerate model-emitted blank context lines that omit the leading space."""

    return " " if line == "" else line


def _parse_hunks(lines: list[str], index: int) -> tuple[list[Hunk], int]:
    hunks: list[Hunk] = []
    while index < len(lines):
        header = lines[index]
        if header.startswith("diff --git "):
            break
        if not header.startswith("@@ "):
            index += 1
            continue
        match = HUNK_RE.match(header)
        if match is None:
            raise ValueError(f"invalid hunk header: {header}")
        body: list[str] = []
        index += 1
        while index < len(lines) and not lines[index].startswith(
            ("diff --git ", "@@ ")
        ):
            if not lines[index].startswith("\\"):
                body.append(_normalize_hunk_line(lines[index]))
            index += 1
        hunks.append(
            Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or "1"),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or "1"),
                lines=tuple(body),
            )
        )
    return hunks, index


def _apply_file_patch(root: Path, file_patch: FilePatch) -> None:
    target_path = root / (file_patch.new_path or file_patch.old_path or "")
    original_path = root / (file_patch.old_path or file_patch.new_path or "")
    original_lines = _read_lines(
        original_path if original_path.exists() else target_path
    )
    new_lines = _apply_hunks(original_lines, file_patch.hunks)
    if file_patch.new_path is None:
        target_path.unlink(missing_ok=True)
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(_join_lines(new_lines), encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _apply_hunks(original: list[str], hunks: tuple[Hunk, ...]) -> list[str]:
    cursor = 0
    result: list[str] = []
    for hunk in hunks:
        start = max(hunk.old_start - 1, 0)
        result.extend(original[cursor:start])
        cursor = start
        for line in hunk.lines:
            prefix, text = line[:1], line[1:]
            if prefix == " ":
                _assert_matches(original, cursor, text)
                result.append(text)
                cursor += 1
            elif prefix == "-":
                _assert_matches(original, cursor, text)
                cursor += 1
            elif prefix == "+":
                result.append(text)
        cursor = min(cursor, len(original))
    result.extend(original[cursor:])
    return result


def _assert_matches(original: list[str], index: int, text: str) -> None:
    if index >= len(original):
        raise ValueError("patch context extends past end of file")
    if original[index] != text:
        raise ValueError(
            f"patch context mismatch: expected {text!r}, found {original[index]!r}"
        )


def _join_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
