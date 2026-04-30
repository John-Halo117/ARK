"""Local-first ARK web console service.

The console is a bounded read/control surface over the existing gateway. It
keeps runtime state in DuckDB and upstream services authoritative while exposing
strict, testable JSON contracts for the browser UI.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

import aiohttp

from ark.ark_schema import (
    SchemaFailure,
    compute_event_hash,
    evaluate_action_gate,
    failure as schema_failure,
    validate_action_constraints,
    validate_event_contract,
)
from ark.duck_client import DuckClient
from ark.event_schema import ArkEvent, EventSource, EventType
from ark.sd_trisca import compute_trisca
from ark.security import (
    clamp_limit,
    sanitize_string,
)
from ark.time_utils import utc_now_iso, utc_timestamp

MAX_CONSOLE_PAGE_SIZE = 200
MAX_CONFIG_BYTES = 131_072
MAX_CONFIG_FILES = 32
MAX_OBSERVED_SERVICES = 12
MAX_TRACE_PAYLOAD_KEYS = 64
MESH_REQUEST_TIMEOUT_SECONDS = 2.0

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_STATIC_DIR = ROOT / "web" / "console"

CONFIG_ALLOWLIST = frozenset(
    {
        "config/manifest.json",
        "config/tiering_rules.json",
        "definitions/actions.yaml",
        "definitions/meta.yaml",
        "definitions/policies.yaml",
        "definitions/routing.yaml",
        "policy/ark_rules.json",
        "policy/autoscaler_rules.json",
        "policy/budgets.json",
        "policy/emitter_rules.json",
        "policy/failure_classes.json",
        "policy/integration_rules.json",
        "policy/mesh_routing_rules.json",
    }
)

OBSERVED_SERVICE_URLS = (
    ("mesh-registry", "http://mesh-registry:7000/api/health"),
    ("autoscaler", "http://autoscaler:7001/api/health"),
    ("nats-monitor", "http://nats:8222/healthz"),
)


@dataclass(frozen=True)
class ConsoleFailure(Exception):
    """Standard ARK failure for console contracts."""

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


def failure(error_code: str, reason: str, context: dict[str, Any] | None = None, recoverable: bool = True) -> dict[str, Any]:
    """Return the standard ARK structured failure object.

    Runtime: O(1). Memory: O(1). Failure cases: none.
    """

    return ConsoleFailure(error_code, reason, context or {}, recoverable).as_dict()


def console_failure_from_schema(exc: SchemaFailure) -> ConsoleFailure:
    """Convert central schema failures to console failures.

    Runtime: O(1). Memory: O(1). Failure cases: none.
    """

    return ConsoleFailure(exc.error_code, exc.reason, exc.context, exc.recoverable)


class WebConsoleService:
    """Bounded console read/control service.

    Inputs: DuckDB client, mesh URL, aiohttp session factory.
    Outputs: JSON-serialisable dictionaries with explicit status/failure fields.
    Runtime: each public method is O(page size or observed service count).
    Memory: bounded by MAX_CONSOLE_PAGE_SIZE and MAX_CONFIG_BYTES.
    Failure cases: returns standard ARK failure objects through callers.
    """

    def __init__(self, db: DuckClient, mesh_url: str):
        self._db = db
        self._mesh_url = mesh_url.rstrip("/")

    async def health_snapshot(self, session: aiohttp.ClientSession) -> dict[str, Any]:
        """Return a bounded system health snapshot.

        Runtime: O(MAX_OBSERVED_SERVICES). Memory: O(MAX_OBSERVED_SERVICES).
        Failure cases: per-service failures are embedded as degraded statuses.
        """

        started = time()
        mesh = await self._fetch_json(session, f"{self._mesh_url}/api/mesh", "mesh")
        services = [
            {
                "name": "gateway",
                "status": "ok",
                "latency_ms": 0,
                "detail": {"surface": "api_gateway"},
            },
            {
                "name": "duckdb",
                "status": "ok" if self._db.conn is not None else "error",
                "latency_ms": 0,
                "detail": self._safe_db_status(),
            },
        ]

        checks = list(OBSERVED_SERVICE_URLS[:MAX_OBSERVED_SERVICES])
        for index in range(min(len(checks), MAX_OBSERVED_SERVICES)):
            name, url = checks[index]
            services.append(await self._probe_service(session, name, url))

        agents = self._mesh_agents(mesh)
        return {
            "status": "ok",
            "generated_at": utc_now_iso(),
            "runtime_ms": int((time() - started) * 1000),
            "services": services,
            "mesh": mesh,
            "agents": agents,
            "caps": {
                "max_services": MAX_OBSERVED_SERVICES,
                "http_timeout_seconds": MESH_REQUEST_TIMEOUT_SECONDS,
                "memory_mib": 8,
            },
        }

    def event_page(
        self,
        *,
        source: str | None,
        event_type: str | None,
        limit: int,
        cursor: int | None,
    ) -> dict[str, Any]:
        """Return a cursor-based event page.

        Runtime: O(limit). Memory: O(limit). Failure cases: invalid cursor/DB errors.
        """

        page = self._db.query_events_page(
            source=sanitize_string(source, 128) if source else None,
            event_type=sanitize_string(event_type, 64) if event_type else None,
            limit=clamp_limit(limit, default=50, ceiling=MAX_CONSOLE_PAGE_SIZE),
            cursor=cursor,
        )
        return {"status": "ok", **page}

    async def agent_registry(self, session: aiohttp.ClientSession) -> dict[str, Any]:
        """Return a normalized capability registry snapshot.

        Runtime: O(service count), bounded by upstream mesh response size.
        Memory: O(service count). Failure cases: mesh unavailable.
        """

        mesh = await self._fetch_json(session, f"{self._mesh_url}/api/mesh", "mesh")
        return {
            "status": "ok",
            "generated_at": utc_now_iso(),
            "agents": self._mesh_agents(mesh),
            "raw_mesh": mesh,
        }

    def decision_trace(self, body: dict[str, Any]) -> dict[str, Any]:
        """Preview event -> TRISCA -> policy -> intent without executing actions.

        Input schema:
            {"event": {"id": str, "kind": str, "entity_id": str,
                       "schema_version": str, "hash": str, "payload": dict,
                       "observations": list[float], "occurred_at": str?}}
        Output schema:
            {"status": "ok", "resolved": dict, "trisca": dict, "intent": dict,
             "decision": dict, "result": {"status": "SIMULATED|BLOCKED", ...},
             "logs": list[dict]}
        Runtime: O(6 + payload keys). Memory: O(payload keys).
        Failure cases: invalid payload, oversized observations, bad field types.
        """

        try:
            event = validate_event_contract(body.get("event"))
            constraints = validate_action_constraints(body.get("constraints", {}), simulation=True)
        except SchemaFailure as exc:
            raise console_failure_from_schema(exc) from exc
        trisca = compute_trisca(event.observations).as_dict()
        intent = self._select_preview_intent(event.event_id, trisca)
        gate = evaluate_action_gate(intent, constraints)
        resolved = {
            "event": {
                **event.as_dict(),
                "occurred_at": sanitize_string(str(body.get("event", {}).get("occurred_at", utc_now_iso())), 64),
            },
            "delta": {"kind": "event_delta", "values": {"event_kind": event.kind, **event.payload}, "log_odds": 0.0},
            "resolved_at": utc_now_iso(),
        }
        return {
            "status": gate["status"],
            "resolved": resolved,
            "trisca": trisca,
            "intent": intent,
            "decision": gate,
            "result": {
                "id": intent["id"],
                "status": gate["status"],
                "action": intent["action"],
                "output": {"executed": gate["executed"], "reason": "console trace preview"},
            },
            "logs": [
                {"stage": "event", "message": "accepted", "context": {"kind": event.kind, "entity_id": event.entity.entity_id}},
                {"stage": "trisca", "message": "s vector computed", "context": {"confidence": trisca["confidence"]}},
                {"stage": "policy", "message": "intent selected", "context": {"action": intent["action"], "score": intent["score"]}},
                {"stage": "gate", "message": gate["status"], "context": {"decision": gate["decision"], "reasons": gate["reasons"]}},
            ],
        }

    def state_snapshot(self) -> dict[str, Any]:
        """Expose current S state as a read-only projection.

        Runtime: O(1). Memory: O(1). Failure cases: missing state returns empty S.
        """

        state = self._db.get_state("console.s") or {}
        return {"status": "ok", "read_only": True, "state": state}

    def action_gate(self, body: dict[str, Any], *, simulation: bool) -> dict[str, Any]:
        """Run the full decision gate for /action and simulation ingest.

        Runtime: O(6 + payload keys + MAX_ALLOWED_ACTIONS). Memory: O(payload).
        Failure cases: schema validation or constraints validation errors.
        """

        try:
            event = validate_event_contract(body.get("event"))
            constraints = validate_action_constraints(body.get("constraints", {}), simulation=simulation)
        except SchemaFailure as exc:
            raise console_failure_from_schema(exc) from exc
        trisca = compute_trisca(event.observations).as_dict()
        intent = self._select_preview_intent(event.event_id, trisca)
        requested_action = sanitize_string(str(body.get("action", intent["action"])).strip(), 128)
        if requested_action:
            intent = {**intent, "action": requested_action}
        gate = evaluate_action_gate(intent, constraints)
        proof = {
            "event_hash": event.event_hash,
            "entity": event.entity.as_dict(),
            "schema_version": event.schema_version,
            "s": trisca["s"],
            "decision": gate,
        }
        return {
            "status": gate["status"],
            "event": event.as_dict(),
            "trisca": trisca,
            "intent": intent,
            "decision": gate,
            "proof": proof,
            "result": {
                "id": intent["id"],
                "status": gate["status"],
                "action": intent["action"],
                "output": {
                    "executed": gate["executed"],
                    "blocked": gate["status"] == "BLOCKED",
                    "simulation": simulation,
                },
            },
            "logs": [
                {"stage": "event", "message": "accepted", "context": {"entity_id": event.entity.entity_id, "hash": event.event_hash}},
                {"stage": "trisca", "message": "s vector computed", "context": {"confidence": trisca["confidence"]}},
                {"stage": "policy", "message": "intent selected", "context": {"action": intent["action"], "score": intent["score"]}},
                {"stage": "gate", "message": gate["status"], "context": {"decision": gate["decision"], "reasons": gate["reasons"]}},
            ],
        }

    def config_index(self) -> dict[str, Any]:
        """Return read-only config files available to the console.

        Runtime: O(MAX_CONFIG_FILES). Memory: O(MAX_CONFIG_FILES).
        Failure cases: none; unreadable files are marked unavailable.
        """

        files = []
        paths = sorted(CONFIG_ALLOWLIST)
        for index in range(min(len(paths), MAX_CONFIG_FILES)):
            rel_path = paths[index]
            path = ROOT / rel_path
            files.append(
                {
                    "path": rel_path,
                    "available": path.is_file(),
                    "bytes": path.stat().st_size if path.is_file() else 0,
                }
            )
        return {"status": "ok", "files": files, "max_bytes": MAX_CONFIG_BYTES}

    def config_file(self, rel_path: str) -> dict[str, Any]:
        """Return one allowlisted config file as read-only text.

        Runtime: O(file bytes), capped to MAX_CONFIG_BYTES. Memory: O(file bytes).
        Failure cases: path not allowlisted, missing file, file too large.
        """

        clean_path = sanitize_string(rel_path, 256)
        if clean_path not in CONFIG_ALLOWLIST:
            raise ConsoleFailure("CONSOLE_CONFIG_FORBIDDEN", "config path is not allowlisted", {"path": clean_path}, False)
        path = ROOT / clean_path
        if not path.is_file():
            raise ConsoleFailure("CONSOLE_CONFIG_MISSING", "config file is not readable", {"path": clean_path}, True)
        size = path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise ConsoleFailure(
                "CONSOLE_CONFIG_TOO_LARGE",
                "config file exceeds console byte budget",
                {"path": clean_path, "bytes": size, "max_bytes": MAX_CONFIG_BYTES},
                False,
            )
        return {
            "status": "ok",
            "path": clean_path,
            "bytes": size,
            "content": path.read_text(encoding="utf-8"),
            "read_only": True,
        }

    def safe_test_ingest(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run full loop in SIMULATION mode and store the replayable proof.

        Runtime: O(payload bytes), capped by validate_payload. Memory: O(payload).
        Failure cases: invalid payload or DB insert failure.
        """

        output = self.action_gate(body, simulation=True)
        event = output["event"]
        trisca = output["trisca"]
        self._db.set_state(
            "console.s",
            {
                "s": trisca["s"],
                "confidence": trisca["confidence"],
                "event_hash": event["hash"],
                "entity_id": event["entity_id"],
                "schema_version": event["schema_version"],
                "updated_at": utc_now_iso(),
            },
        )
        stored = ArkEvent(
            event_id=sanitize_string(str(event["id"]), 128),
            event_type=EventType.STATUS,
            source=EventSource.ARK_CORE,
            timestamp=utc_timestamp(),
            payload={"mode": "SIMULATION", "trace": output},
            decision=output["decision"]["decision"],
            delta={"confidence": float(trisca["confidence"])},
            tags={"surface": "console", "mode": "SIMULATION", "entity_id": str(event["entity_id"])},
        )
        self._db.insert_event(stored)
        return {**output, "stored_event": json.loads(stored.to_json())}

    async def _probe_service(self, session: aiohttp.ClientSession, name: str, url: str) -> dict[str, Any]:
        started = time()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=MESH_REQUEST_TIMEOUT_SECONDS)) as response:
                text = await response.text()
                return {
                    "name": name,
                    "status": "ok" if 200 <= response.status < 300 else "degraded",
                    "latency_ms": int((time() - started) * 1000),
                    "detail": {"http_status": response.status, "body": sanitize_string(text, 512)},
                }
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return {
                "name": name,
                "status": "unavailable",
                "latency_ms": int((time() - started) * 1000),
                "detail": {"error": sanitize_string(str(exc), 512)},
            }

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, label: str) -> dict[str, Any]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=MESH_REQUEST_TIMEOUT_SECONDS)) as response:
                if response.status != 200:
                    return failure(
                        "CONSOLE_UPSTREAM_STATUS",
                        "upstream returned non-ok status",
                        {"label": label, "http_status": response.status},
                        True,
                    )
                data = await response.json()
                return data if isinstance(data, dict) else {"value": data}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return failure("CONSOLE_UPSTREAM_UNAVAILABLE", "upstream service unavailable", {"label": label, "error": str(exc)}, True)

    def _safe_db_status(self) -> dict[str, Any]:
        try:
            return self._db.get_mesh_status()
        except Exception as exc:
            return failure("CONSOLE_DB_STATUS_FAILED", "database status query failed", {"error": str(exc)}, True)

    def _mesh_agents(self, mesh: dict[str, Any]) -> list[dict[str, Any]]:
        service_details = mesh.get("service_details", {})
        if not isinstance(service_details, dict):
            return []
        agents = []
        names = sorted(service_details)
        for index in range(min(len(names), MAX_OBSERVED_SERVICES)):
            name = sanitize_string(str(names[index]), 128)
            detail = service_details.get(name, {})
            if not isinstance(detail, dict):
                detail = {"raw": detail}
            agents.append(
                {
                    "service": name,
                    "instance_count": int(detail.get("instance_count", 0) or 0),
                    "total_load": float(detail.get("total_load", 0.0) or 0.0),
                    "capabilities": detail.get("capabilities", []),
                    "last_failure": detail.get("last_failure"),
                    "raw": detail,
                }
            )
        return agents

    def _select_preview_intent(self, event_id: str, trisca: dict[str, Any]) -> dict[str, Any]:
        confidence = float(trisca["confidence"])
        if confidence >= 0.5:
            rule_id = "high-confidence-observe"
            confidence_value = 0.9
            ev = 1.0
            cost = 0.1
            params = {"mode": "sd-ark", "surface": "policy"}
        else:
            rule_id = "default-observe"
            confidence_value = 0.5
            ev = 0.5
            cost = 0.05
            params = {"mode": "sd-ark", "surface": "fallback"}
        return {
            "id": f"{event_id}:{rule_id}",
            "action": "record",
            "params": params,
            "confidence": confidence_value,
            "ev": ev,
            "cost": cost,
            "score": (confidence_value * ev) - cost,
            "noop": False,
            "matched_rule": rule_id,
        }


def event_hash_for_console(event: dict[str, Any]) -> str:
    """Expose hash helper for UI/tests without duplicating schema logic."""

    return compute_event_hash(event)
