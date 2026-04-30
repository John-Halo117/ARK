"""Single ARK validation and entity-resolution boundary.

All console and action-gate paths use this module so event validation, entity
resolution, hash verification, and action constraints stay deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ark.sd_trisca import MAX_OBSERVATIONS
from ark.security import sanitize_string, validate_payload

MAX_ENTITY_ID_LEN = 256
MAX_SCHEMA_VERSION_LEN = 32
MAX_EVENT_KIND_LEN = 128
MAX_ACTION_NAME_LEN = 128
MAX_ALLOWED_ACTIONS = 16
MAX_PAYLOAD_KEYS = 64
DEFAULT_ACTION_CONFIDENCE_THRESHOLD = 0.5

ENTITY_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,255}$")
SCHEMA_VERSION_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+){0,2}$")
HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class SchemaFailure(ValueError):
    """Standard ARK validation failure."""

    error_code: str
    reason: str
    context: dict[str, Any]
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class EntityRef:
    """Resolved entity identity."""

    entity_id: str
    domain: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"entity_id": self.entity_id, "domain": self.domain, "name": self.name}


@dataclass(frozen=True)
class ValidatedEvent:
    """Strict ARK event contract."""

    event_id: str
    kind: str
    entity: EntityRef
    schema_version: str
    event_hash: str
    payload: dict[str, Any]
    observations: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "kind": self.kind,
            "entity_id": self.entity.entity_id,
            "entity": self.entity.as_dict(),
            "schema_version": self.schema_version,
            "hash": self.event_hash,
            "payload": self.payload,
            "observations": list(self.observations),
        }


@dataclass(frozen=True)
class ActionConstraints:
    """Bounded action gate constraints."""

    confidence_threshold: float
    max_cost: float | None
    allowed_actions: tuple[str, ...]
    simulation: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence_threshold": self.confidence_threshold,
            "max_cost": self.max_cost,
            "allowed_actions": list(self.allowed_actions),
            "simulation": self.simulation,
        }


def failure(error_code: str, reason: str, context: dict[str, Any] | None = None, recoverable: bool = True) -> dict[str, Any]:
    """Return a standard ARK failure.

    Runtime: O(1). Memory: O(1). Failure cases: none.
    """

    return SchemaFailure(error_code, reason, context or {}, recoverable).as_dict()


def validate_event_contract(raw: Any) -> ValidatedEvent:
    """Validate event(entity_id, schema_version, hash) and resolve entity.

    Runtime: O(payload bytes + MAX_OBSERVATIONS). Memory: O(payload bytes).
    Failure cases: missing fields, invalid entity/schema/hash, hash mismatch,
    oversized payload, invalid observations.
    """

    if not isinstance(raw, dict):
        raise SchemaFailure("ARK_EVENT_INVALID", "event must be an object", {}, False)
    event_id = sanitize_string(str(raw.get("id", raw.get("event_id", ""))).strip(), 128)
    kind = sanitize_string(str(raw.get("kind", raw.get("event_type", ""))).strip(), MAX_EVENT_KIND_LEN)
    entity = resolve_entity(raw.get("entity_id"))
    schema_version = _validate_schema_version(raw.get("schema_version"))
    payload = validate_payload(raw.get("payload", {}))
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise SchemaFailure("ARK_EVENT_PAYLOAD_TOO_LARGE", "payload exceeds bounded key count", {"max_keys": MAX_PAYLOAD_KEYS}, False)
    observations = _validate_observations(raw.get("observations", []))
    if not event_id:
        raise SchemaFailure("ARK_EVENT_ID_REQUIRED", "event id is required", {}, False)
    if not kind:
        raise SchemaFailure("ARK_EVENT_KIND_REQUIRED", "event kind is required", {"event_id": event_id}, False)
    expected_hash = compute_event_hash(
        {
            "id": event_id,
            "kind": kind,
            "entity_id": entity.entity_id,
            "schema_version": schema_version,
            "payload": payload,
            "observations": list(observations),
        }
    )
    event_hash = sanitize_string(str(raw.get("hash", "")).strip(), 80)
    if not HASH_RE.match(event_hash):
        raise SchemaFailure("ARK_EVENT_HASH_REQUIRED", "event hash must be sha256:<hex>", {"event_id": event_id}, False)
    if not _constant_time_equal(event_hash, expected_hash):
        raise SchemaFailure(
            "ARK_EVENT_HASH_MISMATCH",
            "event hash does not match canonical event body",
            {"event_id": event_id, "expected_hash": expected_hash},
            False,
        )
    return ValidatedEvent(
        event_id=event_id,
        kind=kind,
        entity=entity,
        schema_version=schema_version,
        event_hash=event_hash,
        payload=payload,
        observations=observations,
    )


def resolve_entity(raw_entity_id: Any) -> EntityRef:
    """Resolve and validate an entity identifier.

    Runtime: O(MAX_ENTITY_ID_LEN). Memory: O(1). Failure cases: missing or
    invalid entity id.
    """

    entity_id = sanitize_string(str(raw_entity_id or "").strip(), MAX_ENTITY_ID_LEN)
    if not ENTITY_ID_RE.match(entity_id):
        raise SchemaFailure("ARK_ENTITY_INVALID", "entity_id is required and must be stable", {"entity_id": entity_id}, False)
    if "." in entity_id:
        domain, name = entity_id.split(".", 1)
    elif ":" in entity_id:
        domain, name = entity_id.split(":", 1)
    else:
        domain, name = "entity", entity_id
    return EntityRef(entity_id=entity_id, domain=domain[:64], name=name[:192])


def compute_event_hash(event_body: dict[str, Any]) -> str:
    """Compute canonical ARK event hash.

    Runtime: O(event bytes). Memory: O(event bytes). Failure cases: TypeError if
    event body cannot be JSON encoded.
    """

    canonical = json.dumps(event_body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_action_constraints(raw: Any, *, simulation: bool) -> ActionConstraints:
    """Validate action gate constraints.

    Runtime: O(MAX_ALLOWED_ACTIONS). Memory: O(MAX_ALLOWED_ACTIONS).
    Failure cases: malformed threshold, action list, or max cost.
    """

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SchemaFailure("ARK_CONSTRAINTS_INVALID", "constraints must be an object", {}, False)
    threshold = _bounded_float(raw.get("confidence_threshold", DEFAULT_ACTION_CONFIDENCE_THRESHOLD), "confidence_threshold", 0.0, 1.0)
    max_cost_raw = raw.get("max_cost")
    max_cost = None if max_cost_raw is None else _bounded_float(max_cost_raw, "max_cost", 0.0, 1_000_000.0)
    allowed_raw = raw.get("allowed_actions", [])
    if allowed_raw is None:
        allowed_raw = []
    if not isinstance(allowed_raw, list) or len(allowed_raw) > MAX_ALLOWED_ACTIONS:
        raise SchemaFailure("ARK_ALLOWED_ACTIONS_INVALID", "allowed_actions must be a bounded list", {"max_actions": MAX_ALLOWED_ACTIONS}, False)
    allowed = []
    for index in range(min(len(allowed_raw), MAX_ALLOWED_ACTIONS)):
        action = sanitize_string(str(allowed_raw[index]).strip(), MAX_ACTION_NAME_LEN)
        if not ACTION_RE.match(action):
            raise SchemaFailure("ARK_ALLOWED_ACTION_INVALID", "allowed action is invalid", {"index": index}, False)
        allowed.append(action)
    return ActionConstraints(
        confidence_threshold=threshold,
        max_cost=max_cost,
        allowed_actions=tuple(allowed),
        simulation=simulation,
    )


def evaluate_action_gate(intent: dict[str, Any], constraints: ActionConstraints) -> dict[str, Any]:
    """Evaluate action confidence and constraints.

    Runtime: O(MAX_ALLOWED_ACTIONS). Memory: O(1). Failure cases: none; all
    failures return BLOCKED decisions.
    """

    action = sanitize_string(str(intent.get("action", "")), MAX_ACTION_NAME_LEN)
    confidence = _safe_float(intent.get("confidence", 0.0))
    cost = _safe_float(intent.get("cost", 0.0))
    reasons = []
    if confidence < constraints.confidence_threshold:
        reasons.append("confidence_below_threshold")
    if constraints.max_cost is not None and cost > constraints.max_cost:
        reasons.append("cost_exceeds_constraint")
    if constraints.allowed_actions and action not in constraints.allowed_actions:
        reasons.append("action_not_allowed")
    status = "BLOCKED" if reasons else ("SIMULATED" if constraints.simulation else "ALLOWED")
    return {
        "status": status,
        "decision": "block" if reasons else "allow",
        "reasons": reasons,
        "executed": False,
        "constraints": constraints.as_dict(),
    }


def _validate_schema_version(raw: Any) -> str:
    schema_version = sanitize_string(str(raw or "").strip(), MAX_SCHEMA_VERSION_LEN)
    if not SCHEMA_VERSION_RE.match(schema_version):
        raise SchemaFailure("ARK_SCHEMA_VERSION_INVALID", "schema_version is required and must look like v1", {"schema_version": schema_version}, False)
    return schema_version


def _validate_observations(raw: Any) -> tuple[float, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SchemaFailure("ARK_OBSERVATIONS_INVALID", "observations must be a list", {}, False)
    if len(raw) > MAX_OBSERVATIONS:
        raise SchemaFailure("ARK_OBSERVATIONS_TOO_LARGE", "observations exceed S[6] bound", {"max_observations": MAX_OBSERVATIONS}, False)
    values = []
    for index in range(min(len(raw), MAX_OBSERVATIONS)):
        try:
            values.append(float(raw[index]))
        except (TypeError, ValueError) as exc:
            raise SchemaFailure("ARK_OBSERVATION_INVALID", "observation must be numeric", {"index": index}, False) from exc
    return tuple(values)


def _bounded_float(raw: Any, name: str, min_value: float, max_value: float) -> float:
    value = _safe_float(raw)
    if value < min_value or value > max_value:
        raise SchemaFailure("ARK_CONSTRAINT_OUT_OF_RANGE", f"{name} is out of range", {"min": min_value, "max": max_value}, False)
    return value


def _safe_float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _constant_time_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for index in range(min(len(left), len(right))):
        result |= ord(left[index]) ^ ord(right[index])
    return result == 0
