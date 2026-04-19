"""Tests for ark.mesh_registry module."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ark.mesh_registry import MeshRegistry, ServiceInstance


# ---------------------------------------------------------------------------
# ServiceInstance
# ---------------------------------------------------------------------------

class TestServiceInstance:
    def _make_instance(self, **overrides):
        defaults = {
            "service": "opencode",
            "instance_id": "inst-001",
            "capabilities": ["code.analyze", "code.generate"],
            "metadata": {"version": "1.0"},
            "ttl_seconds": 10,
        }
        defaults.update(overrides)
        return ServiceInstance(**defaults)

    def test_initial_state(self):
        inst = self._make_instance()
        assert inst.service == "opencode"
        assert inst.instance_id == "inst-001"
        assert inst.capabilities == ["code.analyze", "code.generate"]
        assert inst.load == 0.0
        assert inst.healthy is True

    def test_not_expired_initially(self):
        inst = self._make_instance(ttl_seconds=30)
        assert inst.is_expired() is False

    def test_expired_after_ttl(self):
        inst = self._make_instance(ttl_seconds=1)
        inst.last_heartbeat = datetime.utcnow() - timedelta(seconds=5)
        assert inst.is_expired() is True

    def test_to_dict_fields(self):
        inst = self._make_instance()
        d = inst.to_dict()
        assert d["service"] == "opencode"
        assert d["instance_id"] == "inst-001"
        assert d["capabilities"] == ["code.analyze", "code.generate"]
        assert d["load"] == 0.0
        assert d["healthy"] is True
        assert "registered_at" in d
        assert "last_heartbeat" in d
        assert d["metadata"] == {"version": "1.0"}

    def test_default_metadata(self):
        inst = ServiceInstance("svc", "id", ["cap"])
        assert inst.metadata == {}


# ---------------------------------------------------------------------------
# MeshRegistry — registration & routing (mocked NATS)
# ---------------------------------------------------------------------------

class TestMeshRegistry:
    def setup_method(self):
        self.registry = MeshRegistry(nats_url="nats://localhost:4222")
        # Pre-wire a mock JetStream so publish doesn't fail
        self.registry.nc = MagicMock()
        self.registry.js = AsyncMock()

    @pytest.mark.asyncio
    async def test_handle_registration_new_service(self):
        event = {
            "service": "opencode",
            "instance_id": "inst-001",
            "capabilities": ["code.analyze"],
            "ttl": 10,
            "metadata": {},
        }
        await self.registry.handle_registration(event)

        assert "opencode" in self.registry.registry
        assert "inst-001" in self.registry.registry["opencode"]
        assert "code.analyze" in self.registry.capability_index
        assert "inst-001" in self.registry.capability_index["code.analyze"]

    @pytest.mark.asyncio
    async def test_handle_registration_invalid_missing_service(self):
        await self.registry.handle_registration({"instance_id": "x"})
        assert len(self.registry.registry) == 0

    @pytest.mark.asyncio
    async def test_handle_registration_invalid_missing_instance(self):
        await self.registry.handle_registration({"service": "x"})
        assert len(self.registry.registry) == 0

    @pytest.mark.asyncio
    async def test_handle_registration_multiple_capabilities(self):
        event = {
            "service": "opencode",
            "instance_id": "inst-002",
            "capabilities": ["code.analyze", "code.generate", "reasoning.plan"],
            "ttl": 10,
        }
        await self.registry.handle_registration(event)
        for cap in ["code.analyze", "code.generate", "reasoning.plan"]:
            assert "inst-002" in self.registry.capability_index[cap]

    @pytest.mark.asyncio
    async def test_route_capability_no_match(self):
        result = await self.registry.route_capability("nonexistent.cap")
        assert result is None

    @pytest.mark.asyncio
    async def test_route_capability_empty_candidates(self):
        self.registry.capability_index["cap"] = []
        result = await self.registry.route_capability("cap")
        assert result is None

    @pytest.mark.asyncio
    async def test_route_capability_selects_lowest_load(self):
        # Register two instances with different loads
        for iid, load in [("i1", 0.8), ("i2", 0.2)]:
            event = {
                "service": "svc",
                "instance_id": iid,
                "capabilities": ["do.thing"],
                "ttl": 30,
            }
            await self.registry.handle_registration(event)
            self.registry.registry["svc"][iid].load = load

        result = await self.registry.route_capability("do.thing", load_aware=True)
        assert result is not None
        assert result[1] == "i2"  # lower load

    @pytest.mark.asyncio
    async def test_route_capability_skips_unhealthy(self):
        event = {
            "service": "svc",
            "instance_id": "i1",
            "capabilities": ["do.thing"],
            "ttl": 30,
        }
        await self.registry.handle_registration(event)
        self.registry.registry["svc"]["i1"].healthy = False

        result = await self.registry.route_capability("do.thing", load_aware=True)
        assert result is None or result == (None, None)

    @pytest.mark.asyncio
    async def test_route_capability_without_load_awareness(self):
        event = {
            "service": "svc",
            "instance_id": "i1",
            "capabilities": ["do.thing"],
            "ttl": 30,
        }
        await self.registry.handle_registration(event)

        result = await self.registry.route_capability("do.thing", load_aware=False)
        assert result == ("svc", "i1")

    # ---- get_service_info ----

    @pytest.mark.asyncio
    async def test_get_service_info_unknown(self):
        info = await self.registry.get_service_info("ghost")
        assert info["service"] == "ghost"
        assert info["instances"] == []

    @pytest.mark.asyncio
    async def test_get_service_info_with_instances(self):
        event = {
            "service": "svc",
            "instance_id": "i1",
            "capabilities": ["cap"],
            "ttl": 30,
        }
        await self.registry.handle_registration(event)
        info = await self.registry.get_service_info("svc")
        assert info["instance_count"] == 1
        assert len(info["instances"]) == 1

    # ---- get_mesh_status ----

    @pytest.mark.asyncio
    async def test_get_mesh_status_empty(self):
        status = await self.registry.get_mesh_status()
        assert status["services"] == 0
        assert status["instances"] == 0
        assert status["capabilities"] == 0
        assert "timestamp" in status

    @pytest.mark.asyncio
    async def test_get_mesh_status_after_registration(self):
        for iid in ["i1", "i2"]:
            await self.registry.handle_registration({
                "service": "svc",
                "instance_id": iid,
                "capabilities": ["cap"],
                "ttl": 30,
            })
        status = await self.registry.get_mesh_status()
        assert status["services"] == 1
        assert status["instances"] == 2
        assert status["capabilities"] == 1
        assert status["service_details"]["svc"]["instance_count"] == 2
