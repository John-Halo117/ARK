"""Tests for shared audited runtime flow."""

from unittest.mock import AsyncMock

import pytest

from ark.config import GlobalStateBusConfig
from ark.event_schema import EventSource
from ark.gsb import GlobalStateBus, MemoryGSBSink
from ark.runtime_flow import DispatchDescriptor, DispatchRegistry, RuntimeAudit


def _bus():
    sink = MemoryGSBSink()
    cfg = GlobalStateBusConfig(
        enabled=True,
        max_payload_bytes=4096,
        max_tag_count=8,
        default_source=EventSource.ARK_CORE.value,
    )
    return GlobalStateBus(cfg, (sink,)), sink


@pytest.mark.asyncio
async def test_runtime_audit_dispatch_records_request_and_result():
    bus, sink = _bus()
    audit = RuntimeAudit(bus, source=EventSource.ARK_CORE.value, surface="test")
    registry = DispatchRegistry((DispatchDescriptor("demo.run", lambda params: {"status": "ok", "value": params["value"]}),))

    result = await audit.execute(registry, "demo.run", {"value": 1})

    assert result["value"] == 1
    assert [event.payload["gsb_action"] for event in sink.events] == [
        "test.capability.request",
        "test.capability.result",
    ]


@pytest.mark.asyncio
async def test_runtime_audit_unknown_capability_returns_structured_failure():
    bus, sink = _bus()
    audit = RuntimeAudit(bus, source=EventSource.ARK_CORE.value, surface="test")
    registry = DispatchRegistry(())

    result = await audit.execute(registry, "missing.capability", {})

    assert result["status"] == "error"
    assert result["error_code"] == "CAPABILITY_UNKNOWN"
    assert sink.events[0].event_type.value == "error"


@pytest.mark.asyncio
async def test_runtime_audit_publish_json_records_summary():
    bus, sink = _bus()
    audit = RuntimeAudit(bus, source=EventSource.ARK_CORE.value, surface="test")
    target = AsyncMock()

    await audit.publish_json(target, "ark.test.subject", {"ok": True}, "demo.publish")

    target.publish.assert_awaited_once()
    assert sink.events[0].payload["capability"] == "demo.publish"
