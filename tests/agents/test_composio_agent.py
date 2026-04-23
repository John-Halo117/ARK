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
            "external.email",
            "external.github",
            "external.slack",
            "external.notion",
            "external.calendar",
            "external.crm",
            "external.web.fetch",
            "external.web.search",
            "external.maps.geocode",
            "external.maps.distance",
            "system.docker.status",
        ]
        assert self.bridge.capabilities == expected

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.bridge.handle_capability("bogus", {})
        assert "error" in result

    # ---- send_email ----

    @pytest.mark.asyncio
    async def test_send_email_no_api_key(self):
        result = await self.bridge.send_email({
            "to": "a@b.com",
            "subject": "hi",
            "body": "hello",
        })
        assert result["status"] == "error"
        assert result["error_code"] == "ARK_LOCAL_CONNECTOR_NOT_IMPLEMENTED"

    @pytest.mark.asyncio
    async def test_send_email_ignores_composio_api_key(self):
        self.bridge.composio_api_key = "test-key"
        result = await self.bridge.send_email({
            "to": "a@b.com",
            "subject": "hi",
            "body": "hello",
        })
        assert result["status"] == "error"
        assert result["context"]["to"] == "a@b.com"
        assert result["context"]["subject"] == "hi"

    # ---- github_action ----

    @pytest.mark.asyncio
    async def test_github_action(self):
        result = await self.bridge.github_action({"action": "create_issue", "repo": "org/repo"})
        assert result["capability"] == "external.github"
        assert result["context"]["action"] == "create_issue"
        assert result["context"]["repo"] == "org/repo"

    # ---- slack_message ----

    @pytest.mark.asyncio
    async def test_slack_message(self):
        result = await self.bridge.slack_message({"channel": "#general", "message": "hello"})
        assert result["capability"] == "external.slack"
        assert result["context"]["channel"] == "#general"

    # ---- notion_action ----

    @pytest.mark.asyncio
    async def test_notion_action(self):
        result = await self.bridge.notion_action({"action": "create_page", "database": "db-1"})
        assert result["capability"] == "external.notion"
        assert result["context"]["action"] == "create_page"

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
        assert result["context"]["entity"] == "contact"

    @pytest.mark.asyncio
    async def test_maps_distance_local_integration(self):
        result = await self.bridge.handle_capability(
            "external.maps.distance",
            {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1},
        )
        assert result["status"] == "ok"
        assert result["distance_km"] > 100

    @pytest.mark.asyncio
    async def test_web_search_requires_local_endpoint(self):
        result = await self.bridge.handle_capability("external.web.search", {"query": "ark"})
        assert result["status"] == "error"
        assert result["error_code"] == "WEB_SEARCH_UNCONFIGURED"
