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

    def test_initial_ashi_score(self):
        assert self.agent.ashi_score == 100

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.agent.handle_capability("bogus", {})
        assert "error" in result

    # ---- check_anomaly ----

    @pytest.mark.asyncio
    async def test_check_anomaly_insufficient_data(self):
        self.agent.metric_history["cpu"] = [1, 2, 3]  # < 5 samples
        assert await self.agent.check_anomaly("cpu", 100) is False

    @pytest.mark.asyncio
    async def test_check_anomaly_normal_value(self):
        # Build a stable history
        self.agent.metric_history["cpu"] = [50.0] * 20
        assert await self.agent.check_anomaly("cpu", 51.0) is False

    @pytest.mark.asyncio
    async def test_check_anomaly_detects_spike(self):
        self.agent.metric_history["cpu"] = [50.0] * 20
        assert await self.agent.check_anomaly("cpu", 500.0) is True

    @pytest.mark.asyncio
    async def test_check_anomaly_unknown_metric(self):
        assert await self.agent.check_anomaly("nonexistent", 42) is False

    # ---- detect_anomaly ----

    @pytest.mark.asyncio
    async def test_detect_anomaly_normal(self):
        self.agent.metric_history["temp"] = [22.0] * 20
        result = await self.agent.detect_anomaly({"metric": "temp", "value": 22.5})

        assert result["capability"] == "anomaly.detect"
        assert result["is_anomaly"] is False
        assert result["severity"] == "normal"

    @pytest.mark.asyncio
    async def test_detect_anomaly_high(self):
        self.agent.metric_history["temp"] = [22.0] * 20
        result = await self.agent.detect_anomaly({"metric": "temp", "value": 999.0})

        assert result["is_anomaly"] is True
        assert result["severity"] == "high"

    # ---- ingest_metric ----

    @pytest.mark.asyncio
    async def test_ingest_metric_new(self):
        result = await self.agent.ingest_metric({"name": "cpu.load", "value": 42.0})
        assert result["capability"] == "metrics.ingest"
        assert result["metric"] == "cpu.load"
        assert result["samples"] == 1

    @pytest.mark.asyncio
    async def test_ingest_metric_caps_history(self):
        self.agent.metric_history["m"] = list(range(100))
        result = await self.agent.ingest_metric({"name": "m", "value": 999})
        assert result["samples"] == 100  # capped

    # ---- compute_health ----

    @pytest.mark.asyncio
    async def test_compute_health_healthy(self):
        result = await self.agent.compute_health({"metrics": {}})
        assert result["health_score"] == 100
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_compute_health_degraded(self):
        # Pre-load stable history then check with anomalous values
        for m in ["a", "b", "c"]:
            self.agent.metric_history[m] = [10.0] * 20

        result = await self.agent.compute_health({
            "metrics": {"a": 999, "b": 999, "c": 999}
        })
        assert result["status"] in ("degraded", "critical")
        assert result["anomalies"] >= 2

    # ---- compute_ashi ----

    @pytest.mark.asyncio
    async def test_compute_ashi_optimal(self):
        result = await self.agent.compute_ashi({})
        assert result["capability"] == "ashi.compute"
        assert result["ashi_score"] == 100
        assert result["level"] == "optimal"

    @pytest.mark.asyncio
    async def test_compute_ashi_with_anomalies(self):
        # Inject stable history then push an anomalous latest value
        self.agent.metric_history["x"] = [10.0] * 19 + [9999.0]
        result = await self.agent.compute_ashi({})
        assert result["ashi_score"] < 100
