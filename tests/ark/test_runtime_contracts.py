"""Tests for canonical runtime contracts."""

import pytest

from ark.runtime_contracts import ContractValidationError, runtime_contract_registry


def test_runtime_contract_registry_health():
    health = runtime_contract_registry().health()
    assert health["ok"] is True
    assert health["version"] == "v1"
    assert health["contracts"] >= 10


def test_runtime_contract_validates_gateway_call_body():
    payload = runtime_contract_registry().materialize_payload(
        "runtime.gateway.call_body",
        {"request_id": "req-1", "params": {"x": 1}},
    )
    assert payload["request_id"] == "req-1"
    assert payload["params"] == {"x": 1}


def test_runtime_contract_rejects_missing_required_field():
    with pytest.raises(ContractValidationError) as excinfo:
        runtime_contract_registry().materialize_payload(
            "runtime.mesh.registration",
            {"service": "svc", "instance_id": "i1", "capabilities": []},
        )
    assert excinfo.value.failure.error_code == "RUNTIME_CONTRACT_MISSING_FIELD"


def test_runtime_contract_rejects_unexpected_field():
    with pytest.raises(ContractValidationError) as excinfo:
        runtime_contract_registry().materialize_payload(
            "runtime.mesh.heartbeat",
            {
                "service": "svc",
                "instance_id": "i1",
                "load": 0.1,
                "healthy": True,
                "timestamp": "2026-04-23T11:00:00Z",
                "extra": "nope",
            },
        )
    assert excinfo.value.failure.error_code == "RUNTIME_CONTRACT_UNEXPECTED_FIELD"
