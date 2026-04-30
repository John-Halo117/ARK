"""Context-provider contracts and default implementation."""

from __future__ import annotations

from typing import Protocol

from ..memory.ban import BanList
from ..runtime.config import ContextBuildConfig, DEFAULT_CONTEXT_CONFIG
from ..types import ContextBundle, ForgeState, ForgeTask
from .build import build_context, enrich_with_plan


class ContextProvider(Protocol):
    """Contract for building and enriching Forge task context."""

    def build(
        self, repo_root, task: ForgeTask, banlist: BanList, state: ForgeState
    ) -> ContextBundle: ...

    def enrich_with_plan(
        self, context: ContextBundle, plan: dict[str, object]
    ) -> ContextBundle: ...


class DefaultContextProvider:
    """Default code-built context provider."""

    def __init__(self, config: ContextBuildConfig | None = None) -> None:
        self.config = config or DEFAULT_CONTEXT_CONFIG

    def build(
        self, repo_root, task: ForgeTask, banlist: BanList, state: ForgeState
    ) -> ContextBundle:
        return build_context(repo_root, task, banlist, state, config=self.config)

    def enrich_with_plan(
        self, context: ContextBundle, plan: dict[str, object]
    ) -> ContextBundle:
        return enrich_with_plan(context, plan, config=self.config)
