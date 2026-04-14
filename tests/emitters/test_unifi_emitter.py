"""Tests for emitters.unifi_emitter module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from emitters.unifi_emitter import UniFiEmitter


class TestUniFiEmitter:
    def setup_method(self):
        self.emitter = UniFiEmitter()
        self.emitter.nc = MagicMock()
        self.emitter.js = AsyncMock()

    # ---- init ----

    def test_service_name(self):
        assert self.emitter.service_name == "unifi"

    def test_capabilities(self):
        assert "network.devices" in self.emitter.capabilities
        assert "network.health" in self.emitter.capabilities
        assert "wireless.clients" in self.emitter.capabilities

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.emitter.handle_capability("bogus", {})
        assert "error" in result

    # ---- emit_device_online ----

    @pytest.mark.asyncio
    async def test_emit_device_online(self):
        await self.emitter.emit_device_online("d1", "AP-Office", "192.168.1.2")
        self.emitter.js.publish.assert_called_once()
        assert self.emitter.event_count == 1

    # ---- emit_device_status_change ----

    @pytest.mark.asyncio
    async def test_emit_device_status_change(self):
        await self.emitter.emit_device_status_change(
            "d1", "AP-Office", "192.168.1.2", "connected", "disconnected"
        )
        self.emitter.js.publish.assert_called_once()
        assert self.emitter.event_count == 1

    # ---- emit_network_metric ----

    @pytest.mark.asyncio
    async def test_emit_network_metric(self):
        await self.emitter.emit_network_metric("wireless_clients", 15, "count")
        self.emitter.js.publish.assert_called_once()

    # ---- get_devices ----

    @pytest.mark.asyncio
    async def test_get_devices_empty(self):
        result = await self.emitter.get_devices({})
        assert result["total_devices"] == 0
        assert result["devices"] == []

    @pytest.mark.asyncio
    async def test_get_devices_with_tracked(self):
        self.emitter.tracked_devices["d1"] = {"name": "AP", "status": "connected"}
        result = await self.emitter.get_devices({})
        assert result["total_devices"] == 1

    # ---- get_events ----

    @pytest.mark.asyncio
    async def test_get_events(self):
        result = await self.emitter.get_events({})
        assert result["events"] == []

    # ---- get_device_status ----

    @pytest.mark.asyncio
    async def test_get_device_status_found(self):
        self.emitter.tracked_devices["d1"] = {"name": "AP", "status": "connected"}
        result = await self.emitter.get_device_status({"device_id": "d1"})
        assert result["device_id"] == "d1"
        assert result["info"]["name"] == "AP"

    @pytest.mark.asyncio
    async def test_get_device_status_not_found(self):
        result = await self.emitter.get_device_status({"device_id": "ghost"})
        assert "error" in result

    # ---- fetch_devices / fetch_clients without session ----

    @pytest.mark.asyncio
    async def test_fetch_devices_no_session(self):
        self.emitter.session = None
        result = await self.emitter.fetch_devices()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_clients_no_session(self):
        self.emitter.session = None
        result = await self.emitter.fetch_clients()
        assert result == []

    # ---- get_network_health ----

    @pytest.mark.asyncio
    async def test_get_network_health_no_devices(self):
        self.emitter.session = None
        result = await self.emitter.get_network_health({})
        assert result["health_score"] == 100  # 0 devices -> 100 by default
        assert result["status"] == "healthy"

    # ---- authenticate_unifi ----

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self):
        self.emitter.unifi_username = ""
        self.emitter.unifi_password = ""
        # Should not raise
        await self.emitter.authenticate_unifi()
