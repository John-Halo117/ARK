"""Tests for agents.opencode.agent module."""

import pytest

from agents.opencode.agent import OpenCodeAgent


class TestOpenCodeAgent:
    def setup_method(self):
        self.agent = OpenCodeAgent()

    # ---- init ----

    def test_service_name(self):
        assert self.agent.service_name == "opencode"

    def test_capabilities(self):
        expected = [
            "code.analyze",
            "code.transform",
            "code.generate",
            "reasoning.plan",
            "reasoning.decompose",
        ]
        assert self.agent.capabilities == expected

    def test_initial_request_count(self):
        assert self.agent.request_count == 0

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.agent.handle_capability("bogus", {})
        assert "error" in result
        assert "bogus" in result["error"]

    # ---- analyze_code ----

    @pytest.mark.asyncio
    async def test_analyze_code(self):
        params = {"source": "def foo():\n    pass\n", "language": "python"}
        result = await self.agent.analyze_code(params)

        assert result["agent"] == "opencode"
        assert result["capability"] == "code.analyze"
        assert result["language"] == "python"
        assert result["analysis"]["lines"] == 3
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_analyze_code_defaults(self):
        result = await self.agent.analyze_code({})
        assert result["language"] == "python"
        assert result["analysis"]["lines"] == 1  # empty string split gives ['']

    # ---- transform_code ----

    @pytest.mark.asyncio
    async def test_transform_code(self):
        params = {"source": "x = 1", "type": "optimize"}
        result = await self.agent.transform_code(params)

        assert result["capability"] == "code.transform"
        assert result["type"] == "optimize"
        assert result["output"] == "x = 1"

    @pytest.mark.asyncio
    async def test_transform_code_defaults(self):
        result = await self.agent.transform_code({})
        assert result["type"] == "refactor"

    # ---- generate_code ----

    @pytest.mark.asyncio
    async def test_generate_code(self):
        params = {"spec": "hello world function", "language": "rust"}
        result = await self.agent.generate_code(params)

        assert result["capability"] == "code.generate"
        assert result["language"] == "rust"
        assert result["spec"] == "hello world function"

    # ---- plan ----

    @pytest.mark.asyncio
    async def test_plan(self):
        result = await self.agent.plan({"goal": "deploy service"})
        assert result["capability"] == "reasoning.plan"
        assert result["goal"] == "deploy service"
        assert "steps" in result["plan"]

    # ---- decompose ----

    @pytest.mark.asyncio
    async def test_decompose(self):
        result = await self.agent.decompose({"problem": "scale db"})
        assert result["capability"] == "reasoning.decompose"
        assert result["problem"] == "scale db"
        assert isinstance(result["subtasks"], list)
