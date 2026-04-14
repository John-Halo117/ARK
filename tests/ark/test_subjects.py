"""Tests for ark.subjects module — NATS subject constants and helpers."""

from ark.subjects import (
    MESH_REGISTER, MESH_HEARTBEAT, MESH_REGISTERED,
    ANOMALY_DETECTED, SPAWN_CONFIRMED, SYSTEM_ASHI,
    SYSTEM_QUEUE_DEPTH_SUBSCRIBE, SYSTEM_LATENCY_SUBSCRIBE,
    METRICS_SUBSCRIBE,
    EVENT_STATE_CHANGE, EVENT_CLIMATE_TEMPERATURE, EVENT_LIGHT_TOGGLE,
    EVENT_SENSOR_READING, EVENT_MEDIA_PLAYBACK, EVENT_NETWORK_DEVICE,
    call_subject, call_subscribe_subject, reply_subject,
    parse_capability_from_subject, parse_service_from_queue_depth,
)


# ---------------------------------------------------------------------------
# Constants follow ark.<domain>.<action> convention
# ---------------------------------------------------------------------------


class TestConstants:
    def test_mesh_subjects(self):
        assert MESH_REGISTER == "ark.mesh.register"
        assert MESH_HEARTBEAT == "ark.mesh.heartbeat"
        assert MESH_REGISTERED == "ark.mesh.registered"

    def test_event_subjects(self):
        assert EVENT_STATE_CHANGE == "ark.event.state.change"
        assert EVENT_CLIMATE_TEMPERATURE == "ark.event.climate.temperature"
        assert EVENT_LIGHT_TOGGLE == "ark.event.light.toggle"
        assert EVENT_SENSOR_READING == "ark.event.sensor.reading"
        assert EVENT_MEDIA_PLAYBACK == "ark.event.media.playback"
        assert EVENT_NETWORK_DEVICE == "ark.event.network.device"

    def test_system_subjects(self):
        assert SYSTEM_ASHI == "ark.system.ashi"
        assert SYSTEM_QUEUE_DEPTH_SUBSCRIBE == "ark.system.queue_depth.*"
        assert SYSTEM_LATENCY_SUBSCRIBE == "ark.system.latency.*"

    def test_spawn_subjects(self):
        assert SPAWN_CONFIRMED == "ark.spawn.confirmed"

    def test_anomaly_subjects(self):
        assert ANOMALY_DETECTED == "ark.anomaly.detected"

    def test_metrics_subscribe_uses_multi_token_wildcard(self):
        assert METRICS_SUBSCRIBE == "ark.metrics.>"

    def test_all_constants_start_with_ark(self):
        """Every constant must follow ark.<domain>.* convention."""
        for name in [
            MESH_REGISTER, MESH_HEARTBEAT, MESH_REGISTERED,
            EVENT_STATE_CHANGE, EVENT_CLIMATE_TEMPERATURE, EVENT_LIGHT_TOGGLE,
            EVENT_SENSOR_READING, EVENT_MEDIA_PLAYBACK, EVENT_NETWORK_DEVICE,
            ANOMALY_DETECTED, SYSTEM_ASHI, SPAWN_CONFIRMED,
        ]:
            assert name.startswith("ark."), f"{name!r} does not start with 'ark.'"

    def test_all_constants_are_lowercase(self):
        for name in [
            MESH_REGISTER, MESH_HEARTBEAT, MESH_REGISTERED,
            EVENT_STATE_CHANGE, EVENT_CLIMATE_TEMPERATURE, EVENT_LIGHT_TOGGLE,
            EVENT_SENSOR_READING, EVENT_MEDIA_PLAYBACK, EVENT_NETWORK_DEVICE,
            ANOMALY_DETECTED, SYSTEM_ASHI, SPAWN_CONFIRMED,
        ]:
            assert name == name.lower(), f"{name!r} is not all-lowercase"


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


class TestCallSubject:
    def test_single_token_capability(self):
        assert call_subject("opencode", "analyze") == "ark.call.opencode.analyze"

    def test_dotted_capability(self):
        assert call_subject("opencode", "code.analyze") == "ark.call.opencode.code.analyze"

    def test_composio_external(self):
        assert call_subject("composio", "external.email") == "ark.call.composio.external.email"


class TestCallSubscribeSubject:
    def test_uses_multi_token_wildcard(self):
        assert call_subscribe_subject("opencode") == "ark.call.opencode.>"

    def test_emitter(self):
        assert call_subscribe_subject("homeassistant") == "ark.call.homeassistant.>"


class TestReplySubject:
    def test_basic(self):
        assert reply_subject("req-123") == "ark.reply.req-123"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


class TestParseCapabilityFromSubject:
    def test_dotted_capability(self):
        assert parse_capability_from_subject("ark.call.opencode.code.analyze") == "code.analyze"

    def test_composio_external(self):
        assert parse_capability_from_subject("ark.call.composio.external.email") == "external.email"

    def test_single_token(self):
        assert parse_capability_from_subject("ark.call.svc.cap") == "cap"

    def test_short_subject(self):
        assert parse_capability_from_subject("ark.call.svc") == "unknown"

    def test_deep_capability(self):
        assert parse_capability_from_subject("ark.call.ha.climate.temperature.set") == "climate.temperature.set"


class TestParseServiceFromQueueDepth:
    def test_normal(self):
        assert parse_service_from_queue_depth("ark.system.queue_depth.opencode") == "opencode"

    def test_latency(self):
        assert parse_service_from_queue_depth("ark.system.latency.openwolf") == "openwolf"

    def test_short(self):
        assert parse_service_from_queue_depth("ark.system") == "unknown"
