"""Centralized Forge runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBuildConfig:
    """Swappable deterministic context-selection configuration."""

    noise_parts: tuple[str, ...] = (
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    )
    text_suffixes: tuple[str, ...] = (".py", ".json", ".md", ".txt", ".sh")
    search_roots: tuple[str, ...] = ("forge", "scripts/ai", "tests", "config")
    base_target_budget: int = 6
    max_target_budget: int = 12
    base_excerpt_limit: int = 1200
    max_excerpt_limit: int = 4000

    def target_budget(self, level: int) -> int:
        """Return the bounded target-file budget for one context level."""

        return min(self.max_target_budget, self.base_target_budget + max(0, level) * 2)

    def excerpt_limit(self, level: int) -> int:
        """Return the bounded excerpt budget for one context level."""

        return min(
            self.max_excerpt_limit, self.base_excerpt_limit + max(0, level) * 800
        )


@dataclass(frozen=True)
class ForgePolicyConfig:
    """Centralized engine acceptance and bounded-run defaults."""

    risk_threshold: float = 0.35
    accept_phi_threshold: float = 0.4


@dataclass(frozen=True)
class StructurePolicyConfig:
    """Centralized structure and size limits for Forge code."""

    function_line_limit: int = 80
    function_line_exemptions: tuple[str, ...] = (
        "forge/ui/app.py:launch",
        "forge/ui/browser.py:_browser_page",
    )


@dataclass(frozen=True)
class RuntimeCapabilityConfig:
    """Bounded local tool discovery defaults for Forge."""

    command_timeout_s: int = 3
    docker_version_command: tuple[str, ...] = (
        "docker",
        "version",
        "--format",
        "{{.Server.Version}}",
    )
    docker_compose_command: tuple[str, ...] = (
        "docker",
        "compose",
        "version",
        "--short",
    )
    docker_compose_files: tuple[str, ...] = (
        "docker-compose.yml",
        "compose.yml",
        "compose.yaml",
    )
    repo_mcp_paths: tuple[str, ...] = (".forge/mcp.json", ".mcp.json")
    max_mcp_config_files: int = 4
    max_mcp_config_bytes: int = 262_144


@dataclass(frozen=True)
class ProjectMapConfig:
    """Bounded repo summary defaults for beginner-friendly Forge wiki cards."""

    command_timeout_s: int = 3
    max_files_per_area: int = 300
    highlighted_roots: tuple[tuple[str, str, str], ...] = (
        (
            "ark-core/forge",
            "Forge engine",
            "Self-coding engine, UI, runtime, and gates",
        ),
        ("ark-core/tests", "Safety tests", "Checks that keep Forge behavior stable"),
        ("docker", "Docker setup", "Container and local service helpers"),
        ("scripts", "Launch scripts", "Click/open and setup helpers"),
        (".github", "GitHub setup", "PR checks, workflows, and repo automation"),
    )
    text_suffixes: tuple[str, ...] = (
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".md",
        ".sh",
    )


@dataclass(frozen=True)
class RuntimeBootstrapConfig:
    """Bounded local-runtime startup defaults for low-friction Forge boot."""

    detect_timeout_s: int = 5
    poll_attempts: int = 36
    poll_interval_s: float = 1.0
    watchdog_checks: int = 240
    watchdog_interval_s: float = 15.0
    auto_start_ollama: bool = True
    auto_pull_model: bool = True
    bootstrap_model: str = "qwen3-coder:30b"
    fallback_bootstrap_model: str = "qwen2.5-coder:7b"
    ollama_start_commands: tuple[tuple[str, ...], ...] = (
        ("ollama", "serve"),
        ("ollama.exe", "serve"),
    )
    ollama_pull_command_prefix: tuple[str, ...] = ("ollama", "pull")
    ollama_pull_command_prefixes: tuple[tuple[str, ...], ...] = (
        ("ollama", "pull"),
        ("ollama.exe", "pull"),
    )


@dataclass(frozen=True)
class McpRuntimeConfig:
    """Central local MCP-style tool runtime defaults."""

    command_timeout_s: int = 3
    max_tools: int = 32
    max_output_bytes: int = 65_536
    repo_file_limit: int = 200
    allowed_callers: tuple[str, ...] = ("ollama", "forge", "forge-ui")
    enabled_tools: tuple[str, ...] = (
        "forge.docker.status",
        "forge.repo.files",
        "forge.maps.distance",
    )


@dataclass(frozen=True)
class UiWorkflowPreset:
    """One beginner-friendly workflow preset for the Forge browser app."""

    identifier: str
    label: str
    description: str
    mode_override: str
    context_level: int
    test_mode: str
    auto_loop: bool
    planner_enabled: bool


@dataclass(frozen=True)
class UiToolProfile:
    """One local AI-tool-inspired Forge operating style."""

    identifier: str
    label: str
    description: str
    mode_override: str
    context_level: int
    test_mode: str
    auto_loop: bool
    planner_enabled: bool
    redteam_enabled: bool


@dataclass(frozen=True)
class UiActionTemplate:
    """One plain-English operator action exposed by the browser app."""

    identifier: str
    label: str
    description: str
    task: str
    files: str = ""
    category: str = "daily"


@dataclass(frozen=True)
class UiImprovement:
    """One queued product improvement shown in the Forge app."""

    identifier: str
    label: str
    description: str
    priority: str


@dataclass(frozen=True)
class UiStateConfig:
    """Shared UI defaults and bounded persistence settings."""

    default_browser_port: int = 4765
    max_context_level: int = 3
    auto_loop_attempts: int = 4
    max_logs: int = 500
    max_applied: int = 24
    max_history_records: int = 24
    runtime_summary: str = "Checking Ollama..."
    risk_threshold: float = ForgePolicyConfig.risk_threshold
    mode_override: str = "AUTO"
    context_level: int = 0
    test_mode: str = "default"
    tool_profile: str = "codex"
    quickstart: tuple[str, ...] = (
        "Type the change you want.",
        "Press Start.",
        "Review the proposed change before using it.",
    )
    example_tasks: tuple[str, ...] = (
        "Fix the failing tests without changing product behavior.",
        "Make the error message easier to understand for a user.",
        "Add a small regression test for the current bug.",
        "Clean up this screen without changing the underlying logic.",
    )
    command_legend: tuple[tuple[str, str], ...] = (
        ("Start", "Keep going until Forge finds a safe stopping point"),
        ("Try Once", "Run one short pass and stop"),
        ("Stop", "Ask Forge to stop after the current pass"),
        ("Use This Change", "Apply the selected safe change"),
        ("Skip This Change", "Discard the current option"),
        ("Check AI", "Recheck the local AI runtime and wake it up if possible"),
        ("resume", "Continue the last interrupted task"),
        ("revert", "Preview the last safe undo"),
        ("revert apply", "Undo the last change Forge applied"),
        ("tests fast", "Prefer a quicker check pass"),
        ("mode tri", "Explore more options before deciding"),
        ("export", "Save the current Forge session to a file"),
    )
    action_templates: tuple[UiActionTemplate, ...] = (
        UiActionTemplate(
            "fix-code",
            "Fix code",
            "Find a small safe patch and verify it.",
            "Find the highest-priority failing code path, make the smallest safe "
            "fix, run checks, and show me the patch before applying it.",
        ),
        UiActionTemplate(
            "repair-setup",
            "Repair setup",
            "Check local AI, Python, Git, Docker, and Forge launchers.",
            "Run a Forge setup doctor pass, explain anything unhealthy in plain "
            "English, and prepare safe fixes for local launcher or runtime files.",
        ),
        UiActionTemplate(
            "check-pr",
            "Check PR",
            "Inspect GitHub CI failures and prepare a safe fix.",
            "Check the current GitHub PR, summarize failing checks, identify the "
            "safest fix, and prepare a local patch.",
            ".github",
        ),
        UiActionTemplate(
            "docker-doctor",
            "Docker doctor",
            "Explain containers, compose files, ports, and health.",
            "Inspect Docker and compose setup, explain what is running, identify "
            "risky config, and prepare safe Dockerfile or compose edits if needed.",
            "Dockerfile docker-compose.yml compose.yml compose.yaml",
        ),
        UiActionTemplate(
            "wiki",
            "Update wiki",
            "Refresh the codebase map in plain English.",
            "Create a concise codebase wiki with main areas, important flows, "
            "risks, and safe edit points.",
        ),
        UiActionTemplate(
            "safe-mode",
            "Safe mode",
            "Restrict Forge to tiny low-risk edits.",
            "Use safe mode: only propose the smallest low-risk change, avoid broad "
            "refactors, and stop for review if confidence is low.",
        ),
        UiActionTemplate(
            "replay",
            "Explain last run",
            "Show what Forge tried and why.",
            "Replay the last Forge session in plain English: what was attempted, "
            "what passed, what failed, and what the next safest step is.",
        ),
        UiActionTemplate(
            "benchmark",
            "Benchmark",
            "Run a small progress check for Forge quality.",
            "Prepare a bounded Forge benchmark plan covering bugfix, test repair, "
            "Docker, and UI polish tasks.",
        ),
        UiActionTemplate(
            "notify",
            "Notifications",
            "Add clear ready/failed desktop notifications.",
            "Add low-noise desktop notifications for ready patches, interrupted "
            "runs, and runtime recovery events.",
        ),
        UiActionTemplate(
            "model-progress",
            "Model progress",
            "Show download and startup progress clearly.",
            "Improve model startup and download progress UI so a non-coder can "
            "see whether Forge is waking AI, downloading a model, or ready.",
        ),
    )
    improvement_plan: tuple[UiImprovement, ...] = (
        UiImprovement(
            "ai-health",
            "AI health indicator",
            "Show Ready, Reconnecting, Downloading, or Needs attention.",
            "P0",
        ),
        UiImprovement(
            "model-progress",
            "Model progress",
            "Show model download/startup progress instead of silent waiting.",
            "P0",
        ),
        UiImprovement(
            "repair-setup",
            "Repair setup button",
            "One click to diagnose and fix local Forge/Ollama setup.",
            "P0",
        ),
        UiImprovement(
            "pr-flow",
            "PR auto-check",
            "Read GitHub CI failures and turn them into Forge tasks.",
            "P1",
        ),
        UiImprovement(
            "docker-cards",
            "Docker doctor cards",
            "Show containers, compose files, ports, and health plainly.",
            "P1",
        ),
        UiImprovement(
            "wiki-index",
            "Searchable codebase wiki",
            "Persist and search a Devin-style project map.",
            "P1",
        ),
        UiImprovement(
            "safe-mode",
            "Tiny-change safe mode",
            "When confidence is low, only allow small reviewable patches.",
            "P1",
        ),
        UiImprovement(
            "session-replay",
            "Session replay",
            "Explain every attempt, decision, and failure reason.",
            "P2",
        ),
        UiImprovement(
            "benchmarks",
            "Quality benchmarks",
            "Track success rate, regressions, and time to useful diff.",
            "P2",
        ),
        UiImprovement(
            "notifications",
            "Desktop notifications",
            "Tell the user when a patch is ready or runtime recovered.",
            "P2",
        ),
    )
    workflow_presets: tuple[UiWorkflowPreset, ...] = (
        UiWorkflowPreset(
            "quick",
            "Quick fix",
            "Fastest safe pass for small changes",
            "SIMPLE",
            0,
            "fast",
            False,
            False,
        ),
        UiWorkflowPreset(
            "balanced",
            "Safe fix",
            "Best default for normal coding tasks",
            "AUTO",
            1,
            "default",
            True,
            False,
        ),
        UiWorkflowPreset(
            "deep",
            "Deep review",
            "More context and more checking for tricky work",
            "TRISECT",
            2,
            "full",
            True,
            True,
        ),
    )
    tool_profiles: tuple[UiToolProfile, ...] = (
        UiToolProfile(
            "codex",
            "Codex",
            "Balanced local coding loop with visible diffs and checks",
            "AUTO",
            1,
            "default",
            True,
            False,
            True,
        ),
        UiToolProfile(
            "aider",
            "Aider",
            "Patch-first pairing for tight file-focused edits",
            "SIMPLE",
            1,
            "fast",
            False,
            False,
            True,
        ),
        UiToolProfile(
            "composio",
            "Composio",
            "Local connector hub for Docker, MCP configs, maps, and web tools",
            "AUTO",
            2,
            "default",
            True,
            True,
            True,
        ),
        UiToolProfile(
            "devin",
            "Devin",
            "Autonomous plan-run-verify loop for longer tasks",
            "TRISECT",
            2,
            "full",
            True,
            True,
            True,
        ),
        UiToolProfile(
            "continue",
            "Continue",
            "IDE-style focused help with minimal automation",
            "SIMPLE",
            0,
            "fast",
            False,
            False,
            False,
        ),
        UiToolProfile(
            "cursor",
            "Cursor",
            "Fast feature edits with broader context and quick feedback",
            "BISECT",
            1,
            "default",
            True,
            False,
            True,
        ),
    )
    runtime_help_missing: tuple[str, ...] = (
        "Start Ollama with `ollama serve`.",
        "Pull a coding model like `ollama pull qwen3-coder:30b`.",
        "Press Check Runtime and then run your task again.",
    )
    runtime_help_ready: tuple[str, ...] = (
        "Runtime looks ready.",
        "Try a starter task like `fix the failing tests`.",
        "Use `resume` if you interrupted the last run.",
    )


DEFAULT_CONTEXT_CONFIG = ContextBuildConfig()
DEFAULT_POLICY_CONFIG = ForgePolicyConfig()
DEFAULT_STRUCTURE_CONFIG = StructurePolicyConfig()
DEFAULT_RUNTIME_CAPABILITY_CONFIG = RuntimeCapabilityConfig()
DEFAULT_PROJECT_MAP_CONFIG = ProjectMapConfig()
DEFAULT_RUNTIME_BOOTSTRAP_CONFIG = RuntimeBootstrapConfig()
DEFAULT_MCP_RUNTIME_CONFIG = McpRuntimeConfig()
DEFAULT_UI_STATE_CONFIG = UiStateConfig()
