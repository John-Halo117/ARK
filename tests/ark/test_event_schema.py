"""Tests for ark.event_schema module."""

import json
import time
from unittest.mock import patch

import pytest

from ark.event_schema import (
    ArkEvent,
    EventSource,
    EventType,
    LKS,
    create_event,
)


# ---------------------------------------------------------------------------
# EventSource enum
# ---------------------------------------------------------------------------

class TestEventSource:
    def test_values(self):
        assert EventSource.EMITTER_HA == "emitter.homeassistant"
        assert EventSource.EMITTER_JELLYFIN == "emitter.jellyfin"
        assert EventSource.EMITTER_UNIFI == "emitter.unifi"
        assert EventSource.AGENT_OPENCODE == "agent.opencode"
        assert EventSource.AGENT_OPENWOLF == "agent.openwolf"
        assert EventSource.AGENT_COMPOSIO == "agent.composio"
        assert EventSource.ARK_CORE == "ark.core"
        assert EventSource.SYSTEM == "system"

    def test_is_str_subclass(self):
        assert isinstance(EventSource.ARK_CORE, str)

    def test_member_count(self):
        assert len(EventSource) == 8


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------

class TestEventType:
    def test_values(self):
        assert EventType.METRIC == "metric"
        assert EventType.STATE == "state"
        assert EventType.ANOMALY == "anomaly"
        assert EventType.DECISION == "decision"
        assert EventType.ERROR == "error"
        assert EventType.STATUS == "status"

    def test_is_str_subclass(self):
        assert isinstance(EventType.METRIC, str)

    def test_member_count(self):
        assert len(EventType) == 6


# ---------------------------------------------------------------------------
# LKS dataclass
# ---------------------------------------------------------------------------

class TestLKS:
    def _make_lks(self, **overrides):
        defaults = {
            "qts": 0.95,
            "dsi": 0.5,
            "dss": 0.7,
            "dss_kalman": 0.68,
            "phase": "stable",
        }
        defaults.update(overrides)
        return LKS(**defaults)

    def test_to_dict(self):
        lks = self._make_lks()
        d = lks.to_dict()
        assert d == {
            "qts": 0.95,
            "dsi": 0.5,
            "dss": 0.7,
            "dss_kalman": 0.68,
            "phase": "stable",
        }

    def test_from_dict_roundtrip(self):
        lks = self._make_lks(phase="drift")
        d = lks.to_dict()
        restored = LKS.from_dict(d)
        assert restored == lks

    def test_from_dict_values(self):
        d = {"qts": 1.0, "dsi": 0.0, "dss": 0.1, "dss_kalman": 0.2, "phase": "critical"}
        lks = LKS.from_dict(d)
        assert lks.qts == 1.0
        assert lks.phase == "critical"


# ---------------------------------------------------------------------------
# ArkEvent dataclass
# ---------------------------------------------------------------------------

class TestArkEvent:
    def _make_event(self, **overrides):
        defaults = {
            "event_id": "evt-001",
            "event_type": EventType.METRIC,
            "source": EventSource.ARK_CORE,
            "timestamp": 1700000000,
            "payload": {"key": "value"},
        }
        defaults.update(overrides)
        return ArkEvent(**defaults)

    def test_defaults(self):
        evt = self._make_event()
        assert evt.lks is None
        assert evt.decision is None
        assert evt.delta is None
        assert evt.tags is None

    def test_to_json_minimal(self):
        evt = self._make_event()
        raw = evt.to_json()
        data = json.loads(raw)

        assert data["event_id"] == "evt-001"
        assert data["event_type"] == "metric"
        assert data["source"] == "ark.core"
        assert data["timestamp"] == 1700000000
        assert data["payload"] == {"key": "value"}
        assert data["lks"] is None
        assert data["decision"] is None
        assert data["delta"] is None
        assert data["tags"] == {}

    def test_to_json_with_lks(self):
        lks = LKS(qts=0.9, dsi=0.4, dss=0.6, dss_kalman=0.55, phase="drift")
        evt = self._make_event(lks=lks, decision="scale-up", delta={"raw": 1.2})
        data = json.loads(evt.to_json())

        assert data["lks"]["phase"] == "drift"
        assert data["decision"] == "scale-up"
        assert data["delta"] == {"raw": 1.2}

    def test_from_json_roundtrip_minimal(self):
        evt = self._make_event(tags={"env": "test"})
        restored = ArkEvent.from_json(evt.to_json())

        assert restored.event_id == evt.event_id
        assert restored.event_type == evt.event_type
        assert restored.source == evt.source
        assert restored.timestamp == evt.timestamp
        assert restored.payload == evt.payload
        assert restored.tags == {"env": "test"}
        assert restored.lks is None

    def test_from_json_roundtrip_full(self):
        lks = LKS(qts=0.9, dsi=0.4, dss=0.6, dss_kalman=0.55, phase="unstable")
        evt = self._make_event(
            lks=lks,
            decision="hold",
            delta={"pct": 0.05},
            tags={"source": "test"},
        )
        restored = ArkEvent.from_json(evt.to_json())

        assert restored.lks == lks
        assert restored.decision == "hold"
        assert restored.delta == {"pct": 0.05}

    def test_from_json_missing_optional_fields(self):
        raw = json.dumps({
            "event_id": "x",
            "event_type": "error",
            "source": "system",
            "timestamp": 0,
            "payload": {},
        })
        evt = ArkEvent.from_json(raw)
        assert evt.lks is None
        assert evt.decision is None
        assert evt.delta is None
        assert evt.tags == {}


# ---------------------------------------------------------------------------
# create_event factory
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_creates_event_with_auto_id(self):
        evt = create_event(
            event_type=EventType.STATE,
            source=EventSource.EMITTER_HA,
            payload={"temp": 22},
        )
        assert evt.event_id  # non-empty
        assert len(evt.event_id) == 12
        assert evt.event_type == EventType.STATE
        assert evt.source == EventSource.EMITTER_HA
        assert evt.payload == {"temp": 22}
        assert evt.tags == {}

    def test_creates_event_with_explicit_id(self):
        evt = create_event(
            event_type=EventType.ANOMALY,
            source=EventSource.AGENT_OPENWOLF,
            payload={},
            event_id="custom-id",
        )
        assert evt.event_id == "custom-id"

    def test_creates_event_with_tags(self):
        evt = create_event(
            event_type=EventType.DECISION,
            source=EventSource.ARK_CORE,
            payload={"action": "scale"},
            tags={"priority": "high"},
        )
        assert evt.tags == {"priority": "high"}

    def test_timestamp_is_recent(self):
        before = int(time.time())
        evt = create_event(
            event_type=EventType.STATUS,
            source=EventSource.SYSTEM,
            payload={},
        )
        after = int(time.time())
        assert before <= evt.timestamp <= after
