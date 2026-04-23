"""Tests for the ARK Global State Bus."""

from __future__ import annotations

from ark.config import GlobalStateBusConfig
from ark.event_schema import EventSource, EventType
from ark.gsb import GSBRecord, GlobalStateBus, MemoryGSBSink


def test_gsb_records_to_memory_sink():
    sink = MemoryGSBSink(max_events=4)
    bus = GlobalStateBus(_config(), (sink,))

    result = bus.publish(
        GSBRecord(
            action="test.action",
            capability="gateway.status.query",
            payload={"ok": True},
            source=EventSource.ARK_CORE.value,
        )
    )

    assert result.status == "ok"
    assert len(sink.events) == 1
    assert sink.events[0].event_type == EventType.STATUS
    assert sink.events[0].payload["capability"] == "gateway.status.query"


def test_gsb_rejects_invalid_capability():
    bus = GlobalStateBus(_config(), ())

    result = bus.publish(
        GSBRecord(
            action="test.action",
            capability="../bad",
            payload={},
            source=EventSource.ARK_CORE.value,
        )
    )

    assert result.status == "error"
    assert result.error_code == "GSB_RECORD_REJECTED"


def test_gsb_rejects_oversized_payload():
    bus = GlobalStateBus(_config(max_payload_bytes=32), ())

    result = bus.publish(
        GSBRecord(
            action="test.action",
            capability="gateway.status.query",
            payload={"blob": "x" * 128},
            source=EventSource.ARK_CORE.value,
        )
    )

    assert result.status == "error"
    assert result.error_code == "GSB_RECORD_REJECTED"


def test_gsb_disabled_is_noop():
    sink = MemoryGSBSink()
    bus = GlobalStateBus(_config(enabled=False), (sink,))

    result = bus.publish(GSBRecord(action="noop", capability="gateway.status.query"))

    assert result.status == "ok"
    assert result.event_id == "disabled"
    assert sink.events == []


def _config(enabled: bool = True, max_payload_bytes: int = 4096) -> GlobalStateBusConfig:
    return GlobalStateBusConfig(
        enabled=enabled,
        max_payload_bytes=max_payload_bytes,
        max_tag_count=8,
        default_source=EventSource.ARK_CORE.value,
    )
