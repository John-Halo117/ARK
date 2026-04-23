"""Reducer engine for deterministic runtime materialized views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class SnapshotStore(Protocol):
    def save(self, name: str, state: dict[str, Any]) -> None: ...

    def health(self) -> dict[str, Any]: ...


@dataclass
class MemorySnapshotStore:
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, name: str, state: dict[str, Any]) -> None:
        self.snapshots[name] = state

    def health(self) -> dict[str, Any]:
        return {"name": "memory_snapshot_store", "ok": True, "snapshots": len(self.snapshots)}


@dataclass(frozen=True)
class ReducerResult:
    changed: bool
    reducer: str
    state: dict[str, Any]


class Reducer(Protocol):
    name: str

    def initial_state(self) -> dict[str, Any]: ...

    def apply(self, state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> bool: ...


class ReducerEngine:
    def __init__(
        self,
        reducers: tuple[Reducer, ...],
        snapshot_store: SnapshotStore | None = None,
        max_events: int = 10_000,
    ):
        self._reducers = {reducer.name: reducer for reducer in reducers}
        self._states = {name: reducer.initial_state() for name, reducer in self._reducers.items()}
        self._snapshot_store = snapshot_store or MemorySnapshotStore()
        self._max_events = max_events
        self._applied_events = 0
        for name, state in self._states.items():
            self._snapshot_store.save(name, state)

    def apply(self, event_type: str, payload: dict[str, Any]) -> tuple[ReducerResult, ...]:
        results: list[ReducerResult] = []
        self._applied_events = min(self._max_events, self._applied_events + 1)
        for name, reducer in self._reducers.items():
            state = self._states[name]
            changed = reducer.apply(state, event_type, payload)
            if changed:
                self._snapshot_store.save(name, state)
            results.append(ReducerResult(changed=changed, reducer=name, state=state))
        return tuple(results)

    def replay(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        bounded_events = events[: self._max_events]
        for event_type, payload in bounded_events:
            self.apply(event_type, payload)

    def view(self, reducer_name: str) -> dict[str, Any]:
        return self._states[reducer_name]

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "reducers": sorted(self._reducers),
            "applied_events": self._applied_events,
            "snapshot_store": self._snapshot_store.health(),
        }


@dataclass(frozen=True)
class MeshViewReducer:
    name: str = "mesh.runtime"

    def initial_state(self) -> dict[str, Any]:
        return {"registry": {}, "capability_index": {}}

    def apply(self, state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> bool:
        registry = state["registry"]
        capability_index = state["capability_index"]
        if event_type == "mesh.registration":
            service = payload["service"]
            instance_id = payload["instance_id"]
            registry.setdefault(service, {})
            registry[service][instance_id] = payload["instance"]
            for capability in getattr(payload["instance"], "capabilities", []):
                capability_index.setdefault(capability, [])
                if instance_id not in capability_index[capability]:
                    capability_index[capability].append(instance_id)
            return True
        if event_type == "mesh.heartbeat":
            service = payload["service"]
            instance_id = payload["instance_id"]
            if service in registry and instance_id in registry[service]:
                instance = registry[service][instance_id]
                instance.last_heartbeat = payload["last_heartbeat"]
                instance.load = payload["load"]
                instance.healthy = payload["healthy"]
                return True
            return False
        if event_type == "mesh.instance.expired":
            service = payload["service"]
            instance_id = payload["instance_id"]
            if service in registry and instance_id in registry[service]:
                del registry[service][instance_id]
                if not registry[service]:
                    del registry[service]
                for capability in list(capability_index):
                    capability_index[capability] = [candidate for candidate in capability_index[capability] if candidate != instance_id]
                    if not capability_index[capability]:
                        del capability_index[capability]
                return True
            return False
        return False


@dataclass(frozen=True)
class AutoscalerViewReducer:
    name: str = "autoscaler.runtime"

    def initial_state(self) -> dict[str, Any]:
        return {"instances": {}, "demand": {}, "latency": {}, "last_decision": {}}

    def apply(self, state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> bool:
        if event_type == "autoscaler.demand":
            state["demand"][payload["service"]] = payload["depth"]
            return True
        if event_type == "autoscaler.latency":
            state["latency"][payload["service"]] = payload["latency_ms"]
            return True
        if event_type == "autoscaler.instance_spawned":
            instances = state["instances"].setdefault(payload["service"], [])
            instances.append(payload["container_id"])
            return True
        if event_type == "autoscaler.instance_terminated":
            instances = state["instances"].get(payload["service"], [])
            if payload["container_id"] in instances:
                instances.remove(payload["container_id"])
                return True
            return False
        if event_type == "autoscaler.decision":
            state["last_decision"][payload["service"]] = payload["decision"]
            return True
        return False


@dataclass(frozen=True)
class KeyedItemsReducer:
    name: str
    key_field: str
    upsert_event: str
    remove_event: str = ""

    def initial_state(self) -> dict[str, Any]:
        return {"items": {}}

    def apply(self, state: dict[str, Any], event_type: str, payload: dict[str, Any]) -> bool:
        items = state["items"]
        if event_type == self.upsert_event:
            items[payload[self.key_field]] = payload["value"]
            return True
        if self.remove_event and event_type == self.remove_event:
            removed = items.pop(payload[self.key_field], None)
            return removed is not None
        return False
