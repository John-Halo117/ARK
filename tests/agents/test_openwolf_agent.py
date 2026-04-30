"""Tests for agents.openwolf.agent module."""

import pytest

from agents.openwolf.agent import OpenWolfAgent


class TestOpenWolfAgent:
    def setup_method(self):
        self.agent = OpenWolfAgent()

    # ---- init ----

    def test_service_name(self):
        assert self.agent.service_name == "openwolf"

    def test_capabilities(self):
        expected = [
            "anomaly.detect",
            "system.health",
            "metrics.ingest",
            "ashi.compute",
        ]
        assert self.agent.capabilities == expected

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.agent.handle_capability("bogus", {})
        assert "error" in result

    # ---- detect_anomaly ----

    @pytest.mark.asyncio
    async def test_detect_anomaly_plans_tool(self):
        params = {"metric": "temp", "value": 22.5}
        result = await self.agent.detect_anomaly(params)

        assert result["capability"] == "anomaly.detect"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.stats.anomaly", "args": params}

    # ---- ingest_metric ----

    @pytest.mark.asyncio
    async def test_ingest_metric_plans_tool(self):
        params = {"name": "cpu.load", "value": 42.0}
        result = await self.agent.ingest_metric(params)
        assert result["capability"] == "metrics.ingest"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.metrics.ingest", "args": params}

    # ---- compute_health ----

    @pytest.mark.asyncio
    async def test_compute_health_plans_tool(self):
        params = {"metrics": {"a": 999, "b": 999, "c": 999}}
        result = await self.agent.compute_health(params)
        assert result["capability"] == "system.health"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.system.health", "args": params}

    # ---- compute_ashi ----

    @pytest.mark.asyncio
    async def test_compute_ashi_plans_trisca_tool(self):
        result = await self.agent.compute_ashi({"data": [1, 2, 3]})
        assert result["capability"] == "ashi.compute"
        step = result["plans"][0]["steps"][0]
        assert step == {"tool": "tool.trisca.compute", "args": {"data": [1, 2, 3]}}
