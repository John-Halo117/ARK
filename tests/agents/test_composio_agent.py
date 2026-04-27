"""Tests for agents.composio.agent module."""

import os
from unittest.mock import patch

import pytest

from agents.composio.agent import ComposioBridge


class TestComposioBridge:
    def setup_method(self):
        # Ensure no real API key leaks in
        with patch.dict(os.environ, {"COMPOSIO_API_KEY": ""}, clear=False):
            self.bridge = ComposioBridge()

    # ---- init ----

    def test_service_name(self):
        assert self.bridge.service_name == "composio"

    def test_capabilities(self):
        expected = [
            "external.web.fetch",
            "external.web.search",
            "external.maps.geocode",
            "external.maps.distance",
        ]
        assert self.bridge.capabilities == expected

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.bridge.handle_capability("bogus", {})
        assert "error" in result

    # ---- legacy cloud actions removed ----

    @pytest.mark.asyncio
    async def test_send_email_no_api_key(self):
        result = await self.bridge.send_email(
            {
                "to": "a@b.com",
                "subject": "hi",
                "body": "hello",
            }
        )
        assert result["status"] == "error"
        assert result["error_code"] == "LOCAL_TOOL_MOVED_TO_FORGE"

    @pytest.mark.asyncio
    async def test_send_email_ignores_composio_api_key(self):
        self.bridge.composio_api_key = "test-key"
        result = await self.bridge.send_email(
            {
                "to": "a@b.com",
                "subject": "hi",
                "body": "hello",
            }
        )
        assert result["status"] == "error"

    # ---- github_action ----

    @pytest.mark.asyncio
    async def test_github_action(self):
        result = await self.bridge.github_action(
            {"action": "create_issue", "repo": "org/repo"}
        )
        assert result["capability"] == "external.github"
        assert result["status"] == "error"

    # ---- slack_message ----

    @pytest.mark.asyncio
    async def test_slack_message(self):
        result = await self.bridge.slack_message(
            {"channel": "#general", "message": "hello"}
        )
        assert result["capability"] == "external.slack"
        assert result["status"] == "error"

    # ---- notion_action ----

    @pytest.mark.asyncio
    async def test_notion_action(self):
        result = await self.bridge.notion_action(
            {"action": "create_page", "database": "db-1"}
        )
        assert result["capability"] == "external.notion"
        assert result["status"] == "error"

    # ---- calendar_action ----

    @pytest.mark.asyncio
    async def test_calendar_action(self):
        result = await self.bridge.calendar_action({"action": "create_event"})
        assert result["capability"] == "external.calendar"

    # ---- crm_action ----

    @pytest.mark.asyncio
    async def test_crm_action(self):
        result = await self.bridge.crm_action({"action": "update", "entity": "contact"})
        assert result["capability"] == "external.crm"
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_local_tool_profile_dispatch(self):
        params = {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1}
        result = await self.bridge.handle_capability("external.maps.distance", params)
        assert result["capability"] == "external.maps.distance"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.geo.distance", "args": params}

    @pytest.mark.asyncio
    async def test_web_fetch_plans_tool(self):
        params = {"url": "https://example.com"}
        result = await self.bridge.handle_capability("external.web.fetch", params)
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.data.fetch", "args": params}

    @pytest.mark.asyncio
    async def test_web_search_plans_tool(self):
        params = {"query": "local maps"}
        result = await self.bridge.handle_capability("external.web.search", params)
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.data.fetch", "args": params}

    @pytest.mark.asyncio
    async def test_geocode_plans_tool(self):
        params = {"address": "Seattle, WA"}
        result = await self.bridge.handle_capability("external.maps.geocode", params)
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.geo.geocode", "args": params}
