"""Tests for runtime reducer engine."""

from ark.reducers import (
    AutoscalerViewReducer,
    KeyedItemsReducer,
    MeshViewReducer,
    ReducerEngine,
)
from ark.mesh_registry import ServiceInstance


def test_mesh_reducer_replays_registration_and_heartbeat():
    engine = ReducerEngine((MeshViewReducer(),))
    instance = ServiceInstance("svc", "i1", ["do.thing"], {}, 10)

    engine.replay(
        [
            ("mesh.registration", {"service": "svc", "instance_id": "i1", "instance": instance}),
            ("mesh.heartbeat", {"service": "svc", "instance_id": "i1", "last_heartbeat": instance.last_heartbeat, "load": 0.2, "healthy": True}),
        ]
    )

    view = engine.view("mesh.runtime")
    assert "svc" in view["registry"]
    assert view["registry"]["svc"]["i1"].load == 0.2
    assert view["capability_index"]["do.thing"] == ["i1"]


def test_autoscaler_reducer_tracks_instances_and_decisions():
    engine = ReducerEngine((AutoscalerViewReducer(),))
    engine.apply("autoscaler.instance_spawned", {"service": "opencode", "container_id": "c1"})
    engine.apply("autoscaler.decision", {"service": "opencode", "decision": "scale_up"})

    view = engine.view("autoscaler.runtime")
    assert view["instances"]["opencode"] == ["c1"]
    assert view["last_decision"]["opencode"] == "scale_up"


def test_keyed_items_reducer_removes_items():
    engine = ReducerEngine(
        (
            KeyedItemsReducer(
                name="items",
                key_field="entity_id",
                upsert_event="entity.upsert",
                remove_event="entity.remove",
            ),
        )
    )
    engine.apply("entity.upsert", {"entity_id": "sensor.a", "value": {"state": "10"}})
    engine.apply("entity.remove", {"entity_id": "sensor.a"})
    assert engine.view("items")["items"] == {}
