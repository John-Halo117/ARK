"""Tests for the local ARK web console contracts."""

from __future__ import annotations

import pytest

from ark.duck_client import DuckClient
from ark.event_schema import EventSource, EventType, create_event
from ark.ark_schema import compute_event_hash
from ark.web_console import ConsoleFailure, WebConsoleService, failure


def _event(
    *,
    event_id: str = "evt",
    observations: list[float] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = {
        "id": event_id,
        "kind": "status",
        "entity_id": "console.preview",
        "schema_version": "v1",
        "payload": payload or {"surface": "console"},
        "observations": observations or [0.8, 0.7, 0.6],
    }
    body["hash"] = compute_event_hash(body)
    return body


def test_console_failure_shape_is_standard():
    error = failure("EXAMPLE", "example failure", {"field": "x"}, False)

    assert error == {
        "status": "error",
        "error_code": "EXAMPLE",
        "reason": "example failure",
        "context": {"field": "x"},
        "recoverable": False,
    }


def test_event_page_is_bounded_and_cursor_based(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    for index in range(3):
        db.insert_event(
            create_event(
                EventType.STATUS,
                EventSource.ARK_CORE,
                {"index": index},
                event_id=f"event-{index}",
            )
        )

    page = service.event_page(source=None, event_type=None, limit=2, cursor=None)

    assert page["status"] == "ok"
    assert page["count"] == 2
    assert page["next_cursor"] is not None


def test_decision_trace_rejects_oversized_observations(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    with pytest.raises(ConsoleFailure) as excinfo:
        service.decision_trace(
            {
                "event": {
                    **_event(payload={}),
                    "observations": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
                }
            }
        )

    assert excinfo.value.error_code == "ARK_OBSERVATIONS_TOO_LARGE"


def test_decision_trace_returns_preview_not_execution(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    trace = service.decision_trace(
        {
            "event": _event(),
            "constraints": {"confidence_threshold": 0.5, "allowed_actions": ["record"]},
        }
    )

    assert trace["status"] == "SIMULATED"
    assert trace["trisca"]["confidence"] >= 0
    assert trace["intent"]["action"] == "record"
    assert trace["decision"]["decision"] == "allow"
    assert trace["result"]["status"] == "SIMULATED"
    assert trace["result"]["output"]["executed"] is False


def test_decision_trace_rejects_missing_hash(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")
    event = _event()
    del event["hash"]

    with pytest.raises(ConsoleFailure) as excinfo:
        service.decision_trace({"event": event})

    assert excinfo.value.error_code == "ARK_EVENT_HASH_REQUIRED"


def test_action_gate_blocks_low_confidence_without_execution(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    output = service.action_gate(
        {
            "event": _event(observations=[0.0, 0.0, 0.0]),
            "action": "record",
            "constraints": {"confidence_threshold": 0.95, "allowed_actions": ["record"]},
        },
        simulation=False,
    )

    assert output["status"] == "BLOCKED"
    assert output["decision"]["reasons"] == ["confidence_below_threshold"]
    assert output["result"]["output"]["executed"] is False


def test_test_ingest_runs_simulation_and_updates_readonly_state(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    output = service.safe_test_ingest(
        {
            "event": _event(event_id="sim-evt"),
            "action": "record",
            "constraints": {"confidence_threshold": 0.5, "allowed_actions": ["record"]},
        }
    )

    state = service.state_snapshot()
    assert output["status"] == "SIMULATED"
    assert output["result"]["output"]["simulation"] is True
    assert state["read_only"] is True
    assert state["state"]["entity_id"] == "console.preview"


def test_config_file_rejects_non_allowlisted_path(tmp_path):
    db = DuckClient(str(tmp_path / "ark.duckdb"))
    service = WebConsoleService(db, "http://mesh")

    with pytest.raises(ConsoleFailure) as excinfo:
        service.config_file("../secrets.env")

    assert excinfo.value.error_code == "CONSOLE_CONFIG_FORBIDDEN"
