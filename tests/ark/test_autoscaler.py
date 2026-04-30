"""Tests for ark.autoscaler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ark.autoscaler import Autoscaler


class TestAutoscaler:
    def setup_method(self):
        self.scaler = Autoscaler(nats_url="nats://localhost:4222")
        self.scaler.nc = MagicMock()
        self.scaler.js = AsyncMock()

    # ---- init / config ----

    def test_spawn_config_services(self):
        assert "opencode" in self.scaler.spawn_config
        assert "openwolf" in self.scaler.spawn_config
        assert "composio" in self.scaler.spawn_config

    def test_spawn_config_fields(self):
        cfg = self.scaler.spawn_config["opencode"]
        assert "image" in cfg
        assert "cpu_limit" in cfg
        assert "memory_limit" in cfg
        assert "min_instances" in cfg
        assert "max_instances" in cfg
        assert "queue_threshold" in cfg
        assert "latency_threshold" in cfg

    # ---- check_scaling ----

    @pytest.mark.asyncio
    async def test_check_scaling_unknown_service(self):
        # Should not raise for unknown service
        await self.scaler.check_scaling("nonexistent")

    @pytest.mark.asyncio
    async def test_check_scaling_scale_up_on_demand(self):
        self.scaler.service_demand["opencode"] = 100  # above threshold of 10
        self.scaler.service_instances["opencode"] = []

        with patch.object(self.scaler, "spawn_instance", new_callable=AsyncMock) as mock_spawn:
            await self.scaler.check_scaling("opencode")
            mock_spawn.assert_called_once_with("opencode")

    @pytest.mark.asyncio
    async def test_check_scaling_scale_up_on_latency(self):
        self.scaler.service_demand["openwolf"] = 0  # below demand threshold
        self.scaler.service_latency["openwolf"] = 1000  # above latency threshold of 500
        self.scaler.service_instances["openwolf"] = []

        with patch.object(self.scaler, "spawn_instance", new_callable=AsyncMock) as mock_spawn:
            await self.scaler.check_scaling("openwolf")
            mock_spawn.assert_called_once_with("openwolf")

    @pytest.mark.asyncio
    async def test_check_scaling_no_scale_above_max(self):
        cfg = self.scaler.spawn_config["opencode"]
        self.scaler.service_demand["opencode"] = 100
        # Already at max instances
        self.scaler.service_instances["opencode"] = ["c"] * cfg["max_instances"]

        with patch.object(self.scaler, "spawn_instance", new_callable=AsyncMock) as mock_spawn:
            await self.scaler.check_scaling("opencode")
            mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_scaling_scale_down_when_idle(self):
        self.scaler.service_demand["opencode"] = 0
        self.scaler.service_latency["opencode"] = 0
        # More than min_instances
        self.scaler.service_instances["opencode"] = ["c1", "c2", "c3"]

        with patch.object(self.scaler, "terminate_instance", new_callable=AsyncMock) as mock_term:
            await self.scaler.check_scaling("opencode")
            mock_term.assert_called_once_with("opencode")

    @pytest.mark.asyncio
    async def test_check_scaling_no_scale_down_at_min(self):
        cfg = self.scaler.spawn_config["opencode"]
        self.scaler.service_demand["opencode"] = 0
        self.scaler.service_latency["opencode"] = 0
        # At min_instances (1)
        self.scaler.service_instances["opencode"] = ["c"] * cfg["min_instances"]

        with patch.object(self.scaler, "terminate_instance", new_callable=AsyncMock) as mock_term:
            await self.scaler.check_scaling("opencode")
            mock_term.assert_not_called()

    # ---- spawn_instance ----

    @pytest.mark.asyncio
    async def test_spawn_instance_unknown_service(self):
        result = await self.scaler.spawn_instance("nonexistent")
        assert result == ""

    @pytest.mark.asyncio
    async def test_spawn_instance_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "container123\n"

        with patch("ark.autoscaler.subprocess.run", return_value=mock_result):
            container_id = await self.scaler.spawn_instance("opencode")

        assert container_id == "container123"
        assert "opencode" in self.scaler.service_instances
        assert "container123" in self.scaler.service_instances["opencode"]

    @pytest.mark.asyncio
    async def test_spawn_instance_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("ark.autoscaler.subprocess.run", return_value=mock_result):
            container_id = await self.scaler.spawn_instance("opencode")

        assert container_id == ""

    @pytest.mark.asyncio
    async def test_spawn_instance_exception(self):
        with patch("ark.autoscaler.subprocess.run", side_effect=Exception("boom")):
            container_id = await self.scaler.spawn_instance("opencode")
        assert container_id == ""

    # ---- terminate_instance ----

    @pytest.mark.asyncio
    async def test_terminate_instance_empty(self):
        # Should not raise when no instances
        await self.scaler.terminate_instance("opencode")

    @pytest.mark.asyncio
    async def test_terminate_instance_removes_container(self):
        self.scaler.service_instances["opencode"] = ["c1", "c2"]

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("ark.autoscaler.subprocess.run", return_value=mock_result):
            await self.scaler.terminate_instance("opencode")

        assert self.scaler.service_instances["opencode"] == ["c1"]

    # ---- signal handlers ----

    @pytest.mark.asyncio
    async def test_on_queue_depth_signal_updates_demand_and_triggers_scaling(self):
        with patch.object(self.scaler, "check_scaling", new_callable=AsyncMock) as mock_scale:
            await self.scaler._on_queue_depth_signal("opencode", {"depth": 17})
        assert self.scaler.service_demand["opencode"] == 17.0
        mock_scale.assert_awaited_once_with("opencode")

    @pytest.mark.asyncio
    async def test_on_queue_depth_signal_rejects_invalid_depth(self):
        with patch.object(self.scaler, "check_scaling", new_callable=AsyncMock) as mock_scale:
            await self.scaler._on_queue_depth_signal("opencode", {"depth": -1})
        assert "opencode" not in self.scaler.service_demand
        mock_scale.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_latency_signal_updates_latency(self):
        await self.scaler._on_latency_signal("openwolf", {"latency_ms": 450})
        assert self.scaler.service_latency["openwolf"] == 450.0

    @pytest.mark.asyncio
    async def test_on_latency_signal_rejects_invalid_latency(self):
        await self.scaler._on_latency_signal("openwolf", {"latency_ms": "fast"})
        assert "openwolf" not in self.scaler.service_latency
