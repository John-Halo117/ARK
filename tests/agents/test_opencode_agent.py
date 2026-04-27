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
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.code.analyze", "args": params}
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_analyze_code_defaults(self):
        result = await self.agent.analyze_code({})
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.code.analyze", "args": {}}

    # ---- transform_code ----

    @pytest.mark.asyncio
    async def test_transform_code(self):
        params = {"source": "x = 1", "type": "optimize"}
        result = await self.agent.transform_code(params)

        assert result["capability"] == "code.transform"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.code.transform", "args": params}

    @pytest.mark.asyncio
    async def test_transform_code_defaults(self):
        result = await self.agent.transform_code({})
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.code.transform", "args": {}}

    # ---- generate_code ----

    @pytest.mark.asyncio
    async def test_generate_code(self):
        params = {"spec": "hello world function", "language": "rust"}
        result = await self.agent.generate_code(params)

        assert result["capability"] == "code.generate"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.code.generate", "args": params}

    # ---- plan ----

    @pytest.mark.asyncio
    async def test_plan(self):
        params = {"goal": "deploy service"}
        result = await self.agent.plan(params)
        assert result["capability"] == "reasoning.plan"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.reasoning.plan", "args": params}

    # ---- decompose ----

    @pytest.mark.asyncio
    async def test_decompose(self):
        params = {"problem": "scale db"}
        result = await self.agent.decompose(params)
        assert result["capability"] == "reasoning.decompose"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.reasoning.decompose", "args": params}
