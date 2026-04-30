"""Canonical emitter builders backed by runtime contracts and policy data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ark.policy_engine import load_policy_set
from ark.runtime_contracts import (
    ContractValidationError,
    RuntimeContractRegistry,
    runtime_contract_registry,
)
from ark.subjects import (
    EVENT_CLIMATE_TEMPERATURE,
    EVENT_LIGHT_TOGGLE,
    EVENT_MEDIA_PLAYBACK,
    EVENT_NETWORK_DEVICE,
    EVENT_SENSOR_READING,
    EVENT_STATE_CHANGE,
    METRICS_MEDIA_DURATION,
    METRICS_NETWORK,
    METRICS_TEMPERATURE,
)

@dataclass(frozen=True)
class PublishPlan:
    subject: str
    capability: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class HomeAssistantRoute:
    prefix: str
    subject: str
    value_mode: str
    attribute_name: str = ""

_EMITTER_POLICY_PATH = Path(__file__).resolve().parents[1] / "policy" / "emitter_rules.json"
_EMITTER_POLICY = load_policy_set(_EMITTER_POLICY_PATH)
_RUNTIME_REGISTRY = runtime_contract_registry()
_CONTRACT_ALIASES = {
    "homeassistant.state_change": "runtime.emitter.homeassistant.state_change",
    "homeassistant.state_change_envelope": "runtime.emitter.homeassistant.state_change_envelope",
    "metric.reading": "runtime.emitter.metric.reading",
    "unifi.device_online": "runtime.emitter.unifi.device_online",
    "unifi.device_status_changed": "runtime.emitter.unifi.device_status_changed",
    "jellyfin.playback_start": "runtime.emitter.jellyfin.playback_start",
    "jellyfin.playback_changed": "runtime.emitter.jellyfin.playback_changed",
    "jellyfin.playback_stop": "runtime.emitter.jellyfin.playback_stop",
}


class EmitterContractRegistry:
    version = "1.0.0"

    def __init__(self, runtime_registry: RuntimeContractRegistry):
        self._runtime_registry = runtime_registry

    def materialize_payload(self, contract_name: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._runtime_registry.materialize_payload(_CONTRACT_ALIASES.get(contract_name, contract_name), values)
        except ContractValidationError as exc:
            mapped_code = exc.failure.error_code.replace("RUNTIME_", "EMITTER_", 1)
            raise ContractValidationError(mapped_code, exc.failure.reason, exc.failure.context, exc.failure.recoverable) from exc

    def health(self) -> dict[str, Any]:
        return {
            "name": "emitter_contract_registry",
            "ok": True,
            "version": self.version,
            "contracts": len(_CONTRACT_ALIASES),
        }


_REGISTRY = EmitterContractRegistry(_RUNTIME_REGISTRY)

def emitter_contract_registry() -> RuntimeContractRegistry:
    return _REGISTRY


def build_homeassistant_state_change_plans(
    *,
    entity_id: str,
    old_state: str,
    new_state: str,
    attributes: dict[str, Any],
    timestamp: str,
) -> tuple[PublishPlan, ...]:
    route = _homeassistant_route(entity_id)
    typed_payload = _RUNTIME_REGISTRY.materialize_payload(
        "runtime.emitter.homeassistant.state_change",
        {
            "entity_id": entity_id,
            "old_state": old_state,
            "new_state": new_state,
            "value": _route_value(route, new_state, attributes),
            "attributes": attributes,
            "timestamp": timestamp,
            "source": "homeassistant",
        },
    )
    plans = [
        PublishPlan(
            subject=route.subject,
            capability="emitter.event",
            payload=typed_payload,
        )
    ]
    if route.subject != EVENT_STATE_CHANGE:
        envelope_payload = _RUNTIME_REGISTRY.materialize_payload(
            "runtime.emitter.homeassistant.state_change_envelope",
            {
                "type": "homeassistant.state_change",
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
                "payload": typed_payload,
            },
        )
        plans.append(
            PublishPlan(
                subject=EVENT_STATE_CHANGE,
                capability="emitter.event",
                payload=envelope_payload,
            )
        )
    return tuple(plans)


def build_homeassistant_temperature_metric_plan(*, entity_id: str, temperature: float, timestamp: str) -> PublishPlan:
    return PublishPlan(
        subject=METRICS_TEMPERATURE,
        capability="emitter.metric",
        payload=_build_metric_payload(
            name=f"climate.{entity_id}",
            value=temperature,
            unit="celsius",
            timestamp=timestamp,
            source="homeassistant",
        ),
    )


def build_unifi_device_online_plan(*, device_id: str, device_name: str, ip_address: str, timestamp: str) -> PublishPlan:
    return PublishPlan(
        subject=EVENT_NETWORK_DEVICE,
        capability="emitter.event",
        payload=_RUNTIME_REGISTRY.materialize_payload(
            "runtime.emitter.unifi.device_online",
            {
                "event": "device_online",
                "device_id": device_id,
                "device_name": device_name,
                "ip_address": ip_address,
                "timestamp": timestamp,
                "source": "unifi",
            },
        ),
    )


def build_unifi_device_status_change_plan(
    *,
    device_id: str,
    device_name: str,
    ip_address: str,
    old_status: str,
    new_status: str,
    timestamp: str,
) -> PublishPlan:
    return PublishPlan(
        subject=EVENT_NETWORK_DEVICE,
        capability="emitter.event",
        payload=_RUNTIME_REGISTRY.materialize_payload(
            "runtime.emitter.unifi.device_status_changed",
            {
                "event": "device_status_changed",
                "device_id": device_id,
                "device_name": device_name,
                "ip_address": ip_address,
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": timestamp,
                "source": "unifi",
            },
        ),
    )


def build_unifi_network_metric_plan(*, metric_name: str, value: float, unit: str, timestamp: str) -> PublishPlan:
    return PublishPlan(
        subject=METRICS_NETWORK,
        capability="emitter.metric",
        payload=_build_metric_payload(
            name=f"network.{metric_name}",
            value=value,
            unit=unit,
            timestamp=timestamp,
            source="unifi",
        ),
    )


def build_jellyfin_playback_start_plans(
    *,
    session_id: str,
    device: str,
    title: str,
    media_type: str,
    item: dict[str, Any],
    timestamp: str,
) -> tuple[PublishPlan, ...]:
    plans = [
        PublishPlan(
            subject=EVENT_MEDIA_PLAYBACK,
            capability="emitter.event",
            payload=_RUNTIME_REGISTRY.materialize_payload(
                "runtime.emitter.jellyfin.playback_start",
                {
                    "event": "playback_start",
                    "session_id": session_id,
                    "device": device,
                    "title": title,
                    "media_type": media_type,
                    "item": item,
                    "timestamp": timestamp,
                    "source": "jellyfin",
                },
            ),
        )
    ]
    duration_ticks = item.get("RunTimeTicks", 0)
    if isinstance(duration_ticks, (int, float)) and duration_ticks > 0:
        plans.append(
            PublishPlan(
                subject=METRICS_MEDIA_DURATION,
                capability="emitter.metric",
                payload=_build_metric_payload(
                    name=f"media.{media_type}",
                    value=duration_ticks / 10_000_000,
                    unit="seconds",
                    timestamp=timestamp,
                    source="jellyfin",
                ),
            )
        )
    return tuple(plans)


def build_jellyfin_playback_change_plan(
    *,
    session_id: str,
    device: str,
    title: str,
    media_type: str,
    item: dict[str, Any],
    timestamp: str,
) -> PublishPlan:
    return PublishPlan(
        subject=EVENT_MEDIA_PLAYBACK,
        capability="emitter.event",
        payload=_RUNTIME_REGISTRY.materialize_payload(
            "runtime.emitter.jellyfin.playback_changed",
            {
                "event": "playback_changed",
                "session_id": session_id,
                "device": device,
                "title": title,
                "media_type": media_type,
                "item": item,
                "timestamp": timestamp,
                "source": "jellyfin",
            },
        ),
    )


def build_jellyfin_playback_stop_plan(*, session_id: str, device: str, timestamp: str) -> PublishPlan:
    return PublishPlan(
        subject=EVENT_MEDIA_PLAYBACK,
        capability="emitter.event",
        payload=_RUNTIME_REGISTRY.materialize_payload(
            "runtime.emitter.jellyfin.playback_stop",
            {
                "event": "playback_stop",
                "session_id": session_id,
                "device": device,
                "timestamp": timestamp,
                "source": "jellyfin",
            },
        ),
    )


def _build_metric_payload(*, name: str, value: float, unit: str, timestamp: str, source: str) -> dict[str, Any]:
    return _RUNTIME_REGISTRY.materialize_payload(
        "runtime.emitter.metric.reading",
        {
            "name": name,
            "value": value,
            "unit": unit,
            "timestamp": timestamp,
            "source": source,
        },
    )


def _homeassistant_route(entity_id: str) -> HomeAssistantRoute:
    prefix = entity_id.split(".", 1)[0]
    decision = _EMITTER_POLICY.evaluate({"entity_prefix": prefix})
    output = decision.output
    return HomeAssistantRoute(
        prefix=prefix,
        subject=str(output.get("subject", EVENT_STATE_CHANGE)),
        value_mode=str(output.get("value_mode", "new_state")),
        attribute_name=str(output.get("attribute_name", "")),
    )


def _route_value(route: HomeAssistantRoute, new_state: str, attributes: dict[str, Any]) -> Any:
    if route.value_mode == "attribute":
        return attributes.get(route.attribute_name, 0)
    return new_state
