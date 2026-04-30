"""Tests for Forge local MCP registry and policy gate."""

from __future__ import annotations

from pathlib import Path

from forge.mcp import McpToolCall, build_default_mcp_registry


def test_mcp_registry_rejects_unknown_tool(tmp_path: Path):
    registry = build_default_mcp_registry(tmp_path)

    result = registry.execute(McpToolCall("forge.unknown"))

    assert result["status"] == "error"
    assert result["error_code"] == "MCP_UNKNOWN_TOOL"


def test_mcp_registry_blocks_unknown_arguments(tmp_path: Path):
    registry = build_default_mcp_registry(tmp_path)

    result = registry.execute(
        McpToolCall(
            "forge.maps.distance", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1, "x": 1}
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == "MCP_SCHEMA_UNKNOWN"


def test_mcp_maps_distance_is_offline(tmp_path: Path):
    registry = build_default_mcp_registry(tmp_path)

    result = registry.execute(
        McpToolCall("forge.maps.distance", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1})
    )

    assert result["status"] == "ok"
    assert 100 < result["distance_km"] < 120
