"""Code-built context selection for Forge."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

from ..memory.ban import BanList
from ..runtime.config import ContextBuildConfig, DEFAULT_CONTEXT_CONFIG
from ..types import ContextBundle, ForgeState, ForgeTask


def build_context(
    repo_root: Path,
    task: ForgeTask,
    banlist: BanList,
    state: ForgeState,
    *,
    config: ContextBuildConfig = DEFAULT_CONTEXT_CONFIG,
) -> ContextBundle:
    """Build deterministic task context from the repo and recent failures."""

    target_files = _select_target_files(repo_root, task, config=config)
    excerpt_limit = _excerpt_limit(task.context_level, config=config)
    excerpts = {
        path.relative_to(repo_root).as_posix(): _excerpt(path, limit=excerpt_limit)
        for path in target_files
    }
    missing_context = max(0, 4 + task.context_level - len(target_files))
    hotspots = banlist.hot_regions(state.attempt)
    return ContextBundle(
        repo_root=repo_root,
        task=task,
        target_files=tuple(target_files),
        excerpts=excerpts,
        ban_hotspots=hotspots,
        missing_context=missing_context,
    )


def enrich_with_plan(
    context: ContextBundle,
    plan: dict[str, object],
    *,
    config: ContextBuildConfig = DEFAULT_CONTEXT_CONFIG,
) -> ContextBundle:
    """Expand context using planner-selected files."""

    plan_files = [
        _resolve_target(context.repo_root, str(item))
        for item in list(plan.get("target_files", []))
    ]
    merged_files: list[Path] = list(context.target_files)
    for path in plan_files:
        if path is not None and path not in merged_files:
            merged_files.append(path)
    merged_files = merged_files[: config.target_budget(context.task.context_level)]
    excerpts = {
        path.relative_to(context.repo_root).as_posix(): _excerpt(
            path, limit=config.excerpt_limit(context.task.context_level)
        )
        for path in merged_files
    }
    missing_context = max(0, 4 + context.task.context_level - len(merged_files))
    return replace(
        context,
        target_files=tuple(merged_files),
        excerpts=excerpts,
        missing_context=missing_context,
        plan=plan,
    )


def _select_target_files(
    repo_root: Path, task: ForgeTask, *, config: ContextBuildConfig
) -> list[Path]:
    explicit = [_resolve_target(repo_root, item) for item in task.target_files]
    chosen = [path for path in explicit if path is not None]
    if chosen:
        return chosen[: config.target_budget(task.context_level)]
    keywords = _keywords(task.summary, task.todo)
    scored = sorted(
        _score_candidates(repo_root, keywords, level=task.context_level, config=config),
        reverse=True,
    )
    return [path for _, path in scored[: config.target_budget(task.context_level)]]


def _resolve_target(repo_root: Path, raw: str) -> Path | None:
    path = repo_root / raw
    return path if path.exists() and path.is_file() else None


def _keywords(*chunks: str) -> set[str]:
    joined = " ".join(chunks).lower()
    return {
        token
        for token in re.findall(r"[a-zA-Z_]{3,}", joined)
        if token not in {"the", "and"}
    }


def _score_candidates(
    repo_root: Path,
    keywords: set[str],
    *,
    level: int,
    config: ContextBuildConfig,
) -> list[tuple[int, Path]]:
    scored: list[tuple[int, Path]] = []
    for root_name in config.search_roots:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in _iter_files(root, config=config):
            score = _score_path(path, keywords, level=level)
            if score > 0:
                scored.append((score, path))
    return scored


def _eligible(path: Path, *, config: ContextBuildConfig) -> bool:
    return (
        path.is_file()
        and path.suffix in config.text_suffixes
        and not any(part in config.noise_parts for part in path.parts)
    )


def _score_path(path: Path, keywords: set[str], *, level: int) -> int:
    haystack = path.as_posix().lower()
    bonus = 3 if "scripts/ai" in haystack or "/forge/" in haystack else 0
    matches = sum(4 for token in keywords if token in haystack)
    content_bonus = 0
    if level > 0 and keywords:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        content_bonus = sum(min(level + 1, 3) for token in keywords if token in text)
    return matches + bonus + content_bonus


def _iter_files(root: Path, *, config: ContextBuildConfig) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in config.noise_parts]
        current_path = Path(current_root)
        for filename in filenames:
            path = current_path / filename
            if _eligible(path, config=config):
                files.append(path)
    return files


def _excerpt(path: Path, limit: int = 1200) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:limit]


def _target_budget(level: int, *, config: ContextBuildConfig) -> int:
    return config.target_budget(level)


def _excerpt_limit(level: int, *, config: ContextBuildConfig) -> int:
    return config.excerpt_limit(level)
