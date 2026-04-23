"""Global State Bus for bounded, observable ARK state flow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ark.config import GlobalStateBusConfig, load_global_state_bus_config
from ark.event_schema import ArkEvent, EventSource, EventType, create_event
from ark.security import sanitize_string, validate_capability, validate_payload, validate_tags


@dataclass(frozen=True)
class GSBRecord:
    action: str
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    event_type: str = EventType.STATUS.value
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GSBResult:
    status: str
    event_id: str = ""
    error_code: str = ""
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ok":
            return {"status": "ok", "event_id": self.event_id}
        return {
            "status": "error",
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


class GSBSink(Protocol):
    def write(self, event: ArkEvent) -> None: ...

    def health(self) -> dict[str, Any]: ...


@dataclass
class MemoryGSBSink:
    max_events: int = 256
    events: list[ArkEvent] = field(default_factory=list)

    def write(self, event: ArkEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]

    def health(self) -> dict[str, Any]:
        return {"name": "memory", "ok": True, "events": len(self.events)}


@dataclass(frozen=True)
class DuckGSBSink:
    db: Any

    def write(self, event: ArkEvent) -> None:
        self.db.insert_event(event)

    def health(self) -> dict[str, Any]:
        return {"name": "duckdb", "ok": True}


class GlobalStateBus:
    """Validates and records every ARK state/capability feed."""

    def __init__(self, config: GlobalStateBusConfig, sinks: tuple[GSBSink, ...] = ()):
        self._config = config
        self._sinks = sinks

    def publish(self, record: GSBRecord) -> GSBResult:
        if not self._config.enabled:
            return GSBResult(status="ok", event_id="disabled")
        prepared = self._prepare(record)
        if isinstance(prepared, GSBResult):
            return prepared
        return self._write(prepared)

    def error(self, record: GSBRecord, error_code: str, reason: str) -> GSBResult:
        payload = {**record.payload, "error_code": error_code, "reason": reason}
        error_record = GSBRecord(
            action=record.action,
            capability=record.capability,
            payload=payload,
            source=record.source,
            event_type=EventType.ERROR.value,
            tags=record.tags,
        )
        return self.publish(error_record)

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self._config.enabled,
            "sinks": [sink.health() for sink in self._sinks],
        }

    def _prepare(self, record: GSBRecord) -> ArkEvent | GSBResult:
        try:
            payload = self._payload(record)
            return create_event(
                event_type=self._event_type(record.event_type),
                source=self._source(record.source),
                payload=payload,
                tags=self._tags(record.tags),
            )
        except ValueError as exc:
            return _failure("GSB_RECORD_REJECTED", str(exc), {"capability": record.capability})

    def _payload(self, record: GSBRecord) -> dict[str, Any]:
        capability = validate_capability(record.capability)
        action = sanitize_string(record.action, 128)
        payload = validate_payload(record.payload, self._config.max_payload_bytes)
        return {"gsb_action": action, "capability": capability, "data": payload}

    def _source(self, source: str) -> EventSource:
        candidate = source or self._config.default_source
        try:
            return EventSource(candidate)
        except ValueError as exc:
            raise ValueError(f"invalid GSB source: {candidate}") from exc

    def _event_type(self, event_type: str) -> EventType:
        try:
            return EventType(event_type)
        except ValueError as exc:
            raise ValueError(f"invalid GSB event type: {event_type}") from exc

    def _tags(self, tags: dict[str, str]) -> dict[str, str]:
        if len(tags) > self._config.max_tag_count:
            raise ValueError(f"too many GSB tags (max {self._config.max_tag_count})")
        return validate_tags(tags)

    def _write(self, event: ArkEvent) -> GSBResult:
        try:
            for sink in self._sinks:
                sink.write(event)
        except Exception as exc:
            return _failure("GSB_SINK_FAILED", str(exc), {"event_id": event.event_id})
        return GSBResult(status="ok", event_id=event.event_id, recoverable=False)


def build_global_state_bus(*sinks: GSBSink) -> GlobalStateBus:
    return GlobalStateBus(load_global_state_bus_config(), tuple(sinks))


def gsb_error_response(error_code: str, reason: str, context: dict[str, Any]) -> dict[str, Any]:
    return _failure(error_code, reason, context).as_dict()


def _failure(error_code: str, reason: str, context: dict[str, Any]) -> GSBResult:
    return GSBResult(
        status="error",
        error_code=error_code,
        reason=sanitize_string(reason, 1024),
        context=_bounded_context(context),
        recoverable=True,
    )


def _bounded_context(context: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(context, default=str)
    if len(raw.encode()) <= 8192:
        return context
    return {"truncated": True, "bytes": len(raw.encode())}
