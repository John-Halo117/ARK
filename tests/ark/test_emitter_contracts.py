"""Tests for canonical emitter contract builders."""

import pytest

from ark.emitter_contracts import (
    ContractValidationError,
    build_homeassistant_state_change_plans,
    build_jellyfin_playback_start_plans,
    build_unifi_device_status_change_plan,
    emitter_contract_registry,
)
from ark.subjects import (
    EVENT_CLIMATE_TEMPERATURE,
    EVENT_STATE_CHANGE,
    METRICS_MEDIA_DURATION,
)


def test_registry_health_reports_loaded_contracts():
    health = emitter_contract_registry().health()
    assert health["ok"] is True
    assert health["contracts"] >= 8
    assert health["version"] == "1.0.0"


def test_homeassistant_generic_state_change_emits_single_plan():
    plans = build_homeassistant_state_change_plans(
        entity_id="switch.outlet",
        old_state="off",
        new_state="on",
        attributes={},
        timestamp="2026-04-23T10:00:00Z",
    )
    assert len(plans) == 1
    assert plans[0].subject == EVENT_STATE_CHANGE
    assert plans[0].payload["value"] == "on"


def test_homeassistant_climate_state_change_emits_typed_and_general_plans():
    plans = build_homeassistant_state_change_plans(
        entity_id="climate.office",
        old_state="off",
        new_state="heat",
        attributes={"current_temperature": 22.5},
        timestamp="2026-04-23T10:00:00Z",
    )
    assert len(plans) == 2
    assert plans[0].subject == EVENT_CLIMATE_TEMPERATURE
    assert plans[0].payload["value"] == 22.5
    assert plans[1].subject == EVENT_STATE_CHANGE
    assert plans[1].payload["payload"]["entity_id"] == "climate.office"


def test_unifi_status_change_plan_builds_canonical_payload():
    plan = build_unifi_device_status_change_plan(
        device_id="d-1",
        device_name="AP-Office",
        ip_address="192.168.1.2",
        old_status="connected",
        new_status="disconnected",
        timestamp="2026-04-23T10:00:00Z",
    )
    assert plan.payload["event"] == "device_status_changed"
    assert plan.payload["new_status"] == "disconnected"


def test_jellyfin_start_includes_duration_metric_when_available():
    plans = build_jellyfin_playback_start_plans(
        session_id="session-1",
        device="TV",
        title="Movie",
        media_type="Movie",
        item={"RunTimeTicks": 90_000_000},
        timestamp="2026-04-23T10:00:00Z",
    )
    subjects = [plan.subject for plan in plans]
    assert METRICS_MEDIA_DURATION in subjects


def test_contract_rejects_unexpected_fields():
    registry = emitter_contract_registry()
    with pytest.raises(ContractValidationError) as excinfo:
        registry.materialize_payload(
            "unifi.device_online",
            {
                "event": "device_online",
                "device_id": "d-1",
                "device_name": "AP",
                "ip_address": "192.168.1.2",
                "timestamp": "2026-04-23T10:00:00Z",
                "source": "unifi",
                "extra": "nope",
            },
        )
    assert excinfo.value.failure.error_code == "EMITTER_CONTRACT_UNEXPECTED_FIELD"
