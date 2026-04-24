"""ARK-made local MCP-style tools for Forge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..math_utils import KM_TO_MILES, haversine_km, valid_lat, valid_lon
from ..runtime.capabilities import detect_docker
from ..runtime.config import DEFAULT_MCP_RUNTIME_CONFIG, McpRuntimeConfig
from .contracts import McpToolCall, McpToolResult, McpToolSpec, mcp_failure, mcp_success


@dataclass(frozen=True)
class DockerStatusTool:
    repo_root: Path
    config: McpRuntimeConfig = DEFAULT_MCP_RUNTIME_CONFIG

    @property
    def spec(self) -> McpToolSpec:
        return McpToolSpec(
            "forge.docker.status",
            "Report local Docker and Compose readiness without starting containers.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            self.config.command_timeout_s,
            self.config.max_output_bytes,
        )

    def execute(self, _call: McpToolCall) -> McpToolResult:
        status = detect_docker(self.repo_root)
        return mcp_success(self.spec.name, status.as_dict())


@dataclass(frozen=True)
class RepoFilesTool:
    repo_root: Path
    config: McpRuntimeConfig = DEFAULT_MCP_RUNTIME_CONFIG

    @property
    def spec(self) -> McpToolSpec:
        return McpToolSpec(
            "forge.repo.files",
            "List repo files using bounded, noise-filtered local traversal.",
            {
                "type": "object",
                "properties": {"prefix": {"type": "string"}},
                "additionalProperties": False,
            },
            self.config.command_timeout_s,
            self.config.max_output_bytes,
        )

    def execute(self, call: McpToolCall) -> McpToolResult:
        prefix = str(call.arguments.get("prefix", "")).strip()
        root = _safe_root(self.repo_root, prefix)
        if root is None:
            return mcp_failure(
                self.spec.name, "MCP_BAD_PREFIX", "prefix escapes repo root"
            )
        files = _bounded_files(root, self.repo_root, limit=self.config.repo_file_limit)
        return mcp_success(self.spec.name, {"prefix": prefix, "files": files})


@dataclass(frozen=True)
class MapsDistanceTool:
    config: McpRuntimeConfig = DEFAULT_MCP_RUNTIME_CONFIG

    @property
    def spec(self) -> McpToolSpec:
        return McpToolSpec(
            "forge.maps.distance",
            "Compute offline distance between two latitude/longitude points.",
            {
                "type": "object",
                "required": ["lat1", "lon1", "lat2", "lon2"],
                "properties": {
                    "lat1": {"type": "number"},
                    "lon1": {"type": "number"},
                    "lat2": {"type": "number"},
                    "lon2": {"type": "number"},
                },
                "additionalProperties": False,
            },
            self.config.command_timeout_s,
            self.config.max_output_bytes,
        )

    def execute(self, call: McpToolCall) -> McpToolResult:
        parsed = _parse_points(call)
        if isinstance(parsed, McpToolResult):
            return parsed
        distance_km = haversine_km(*parsed)
        return mcp_success(
            self.spec.name,
            {
                "distance_km": round(distance_km, 4),
                "distance_mi": round(distance_km * KM_TO_MILES, 4),
            },
        )


def _safe_root(repo_root: Path, prefix: str) -> Path | None:
    candidate = (repo_root / prefix).resolve()
    repo = repo_root.resolve()
    return candidate if candidate == repo or repo in candidate.parents else None


def _bounded_files(root: Path, repo_root: Path, *, limit: int) -> list[str]:
    if root.is_file():
        return [root.relative_to(repo_root).as_posix()]
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= limit:
            break
        if path.is_file() and not _is_noise(path):
            files.append(path.relative_to(repo_root).as_posix())
    return files


def _is_noise(path: Path) -> bool:
    return any(
        part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in path.parts
    )


def _parse_points(
    call: McpToolCall,
) -> tuple[float, float, float, float] | McpToolResult:
    try:
        lat1 = float(call.arguments["lat1"])
        lon1 = float(call.arguments["lon1"])
        lat2 = float(call.arguments["lat2"])
        lon2 = float(call.arguments["lon2"])
    except (KeyError, TypeError, ValueError):
        return mcp_failure(
            call.name, "MCP_MAPS_BAD_INPUT", "lat1/lon1/lat2/lon2 are required"
        )
    if not all((valid_lat(lat1), valid_lat(lat2), valid_lon(lon1), valid_lon(lon2))):
        return mcp_failure(
            call.name, "MCP_MAPS_OUT_OF_RANGE", "coordinates are out of range"
        )
    return lat1, lon1, lat2, lon2
