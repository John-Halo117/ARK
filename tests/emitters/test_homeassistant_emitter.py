"""Tests for emitters.homeassistant_emitter module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ark.subjects import (
    EVENT_CLIMATE_TEMPERATURE, EVENT_LIGHT_TOGGLE,
    EVENT_SENSOR_READING, EVENT_STATE_CHANGE,
)
from emitters.homeassistant_emitter import HomeAssistantEmitter


class TestHomeAssistantEmitter:
    def setup_method(self):
        self.emitter = HomeAssistantEmitter()
        self.emitter.nc = MagicMock()
        self.emitter.js = AsyncMock()

    # ---- init ----

    def test_service_name(self):
        assert self.emitter.service_name == "homeassistant"

    def test_capabilities(self):
        assert "event.home_assistant" in self.emitter.capabilities
        assert "light.toggle" in self.emitter.capabilities
        assert "climate.temperature" in self.emitter.capabilities

    # ---- handle_capability dispatch ----

    @pytest.mark.asyncio
    async def test_handle_capability_unknown(self):
        result = await self.emitter.handle_capability("bogus", {})
        assert "error" in result

    # ---- emit_state_change topic routing ----

    @pytest.mark.asyncio
    async def test_emit_state_change_climate(self):
        await self.emitter.emit_state_change(
            "climate.livingroom", "off", "heat", {"current_temperature": 22}
        )
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_CLIMATE_TEMPERATURE in topics

    @pytest.mark.asyncio
    async def test_emit_state_change_light(self):
        await self.emitter.emit_state_change("light.kitchen", "off", "on", {})
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_LIGHT_TOGGLE in topics

    @pytest.mark.asyncio
    async def test_emit_state_change_sensor(self):
        await self.emitter.emit_state_change("sensor.humidity", "45", "50", {})
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_SENSOR_READING in topics

    @pytest.mark.asyncio
    async def test_emit_state_change_generic(self):
        await self.emitter.emit_state_change("switch.outlet", "off", "on", {})
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_STATE_CHANGE in topics

    @pytest.mark.asyncio
    async def test_emit_state_change_generic_no_duplicate(self):
        """Generic entities should publish exactly once to EVENT_STATE_CHANGE, not twice."""
        await self.emitter.emit_state_change("switch.outlet", "off", "on", {})
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert topics.count(EVENT_STATE_CHANGE) == 1

    @pytest.mark.asyncio
    async def test_emit_state_change_typed_also_publishes_general(self):
        """Typed entities (climate/light/sensor) should also publish to EVENT_STATE_CHANGE."""
        await self.emitter.emit_state_change("light.desk", "off", "on", {})
        calls = self.emitter.js.publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert EVENT_LIGHT_TOGGLE in topics
        assert EVENT_STATE_CHANGE in topics

    @pytest.mark.asyncio
    async def test_emit_state_change_increments_count(self):
        assert self.emitter.event_count == 0
        await self.emitter.emit_state_change("light.x", "off", "on", {})
        assert self.emitter.event_count == 1

    # ---- get_events ----

    @pytest.mark.asyncio
    async def test_get_events(self):
        self.emitter.tracked_entities["sensor.a"] = {"state": "10"}
        result = await self.emitter.get_events({"limit": 5})
        assert result["capability"] == "event.home_assistant"
        assert result["total_tracked"] == 1

    # ---- get_temperature ----

    @pytest.mark.asyncio
    async def test_get_temperature_found(self):
        self.emitter.tracked_entities["climate.living"] = {
            "state": "heat",
            "attributes": {"current_temperature": 21.5},
        }
        result = await self.emitter.get_temperature({"entity_id": "climate.living"})
        assert result["temperature"] == 21.5

    @pytest.mark.asyncio
    async def test_get_temperature_not_found(self):
        result = await self.emitter.get_temperature({"entity_id": "climate.ghost"})
        assert "error" in result

    # ---- toggle_light ----

    @pytest.mark.asyncio
    async def test_toggle_light_on_to_off(self):
        self.emitter.tracked_entities["light.bed"] = {"state": "on"}
        self.emitter.session = None  # skip actual HTTP
        self.emitter.ha_token = ""
        result = await self.emitter.toggle_light({"entity_id": "light.bed"})
        assert result["old_state"] == "on"
        assert result["new_state"] == "off"

    @pytest.mark.asyncio
    async def test_toggle_light_not_found(self):
        result = await self.emitter.toggle_light({"entity_id": "light.ghost"})
        assert "error" in result

    # ---- get_sensor ----

    @pytest.mark.asyncio
    async def test_get_sensor_found(self):
        self.emitter.tracked_entities["sensor.temp"] = {
            "state": "22",
            "attributes": {"unit": "C"},
        }
        result = await self.emitter.get_sensor({"entity_id": "sensor.temp"})
        assert result["state"] == "22"

    @pytest.mark.asyncio
    async def test_get_sensor_not_found(self):
        result = await self.emitter.get_sensor({"entity_id": "sensor.ghost"})
        assert "error" in result

    # ---- fetch_states ----

    @pytest.mark.asyncio
    async def test_fetch_states_no_session(self):
        self.emitter.session = None
        result = await self.emitter.fetch_states()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_states_no_token(self):
        self.emitter.session = MagicMock()
        self.emitter.ha_token = ""
        result = await self.emitter.fetch_states()
        assert result == []
