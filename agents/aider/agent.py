#!/usr/bin/env python3
"""
Unified Aider agent runtime.
Provides capability handling for opencode, openwolf, and composio profiles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List

try:
    from nats.errors import Error as NATSError
except ImportError:  # pragma: no cover - local import/test environments
    NATSError = RuntimeError

from ark.config import load_composio_config, load_service_runtime_config
from ark.event_schema import EventSource
from ark.forge_planner import ForgePlanner
from ark.gsb import GlobalStateBus, build_global_state_bus
from ark.integrations import IntegrationRegistry, build_local_registry
from ark.math_utils import zscore_anomaly
from ark.maintenance import HealthCheck, ResilientNATSConnection, ShutdownCoordinator
from ark.runtime_contracts import runtime_contract_registry
from ark.runtime_flow import DispatchDescriptor, DispatchRegistry, RuntimeAudit, runtime_failure, summarize_result
from ark.security import sanitize_string
from ark.subjects import (
    MESH_HEARTBEAT,
    MESH_REGISTER,
    parse_capability_from_subject,
    call_subscribe_subject,
    reply_subject,
)
from ark.time_utils import utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AiderAgent")

MAX_AGENT_HEARTBEATS = 100_000
MAX_AGENT_MESSAGES = 100_000
MAX_AGENT_SUBSCRIBE_IDLE_SECONDS = 30.0

PROFILE_CAPABILITIES: Dict[str, List[str]] = {
    "opencode": [
        "code.analyze",
        "code.transform",
        "code.generate",
        "reasoning.plan",
        "reasoning.decompose",
    ],
    "openwolf": [
        "anomaly.detect",
        "system.health",
        "metrics.ingest",
        "ashi.compute",
    ],
    "composio": [
        "external.email",
        "external.github",
        "external.slack",
        "external.notion",
        "external.calendar",
        "external.crm",
        "external.web.fetch",
        "external.web.search",
        "external.maps.geocode",
        "external.maps.distance",
        "system.docker.status",
    ],
}


class AiderAgent:
    """Profiled unified ARK agent."""

    def __init__(self, profile: str):
        if profile not in PROFILE_CAPABILITIES:
            raise ValueError(f"Unsupported aider profile: {profile}")

        runtime = load_service_runtime_config()
        self.service_name = profile
        self.instance_id = runtime.instance_id
        self.nats_url = runtime.nats_url
        self.capabilities = PROFILE_CAPABILITIES[profile]

        self.request_count = 0
        self.nc = None
        self.js = None
        self.gsb: GlobalStateBus = build_global_state_bus()
        self.audit = RuntimeAudit(
            self.gsb,
            source=self._gsb_source(),
            surface="agent",
            default_tags={"service": self.service_name},
        )
        self.contracts = runtime_contract_registry()
        self.planner = ForgePlanner()

        self._nats = ResilientNATSConnection(self.nats_url)
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck(self.service_name)
        self.health.register("nats", lambda: self._nats.is_connected)

        # OpenWolf profile state
        self.metric_history: Dict[str, List[float]] = {}
        self._max_metric_history = 100
        self.ashi_score = 100

        # Composio profile state — only load when needed
        if self.service_name == "composio":
            composio_cfg = load_composio_config()
            self.composio_api_key = composio_cfg.composio_api_key
            self.local_integrations: IntegrationRegistry | None = build_local_registry(gsb=self.gsb)
            self.health.register("local_integrations", self._local_integrations_ready)
        else:
            self.composio_api_key = ""
            self.local_integrations = None

        self.dispatch = DispatchRegistry(self._build_dispatch_descriptors(), contracts=self.contracts)

    async def connect(self):
        self.nc = await self._nats.connect()
        self.js = self._nats.js

    async def register(self):
        event = {
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "metadata": {
                "version": "2.0.0",
                "started_at": utc_now_iso(),
                "runtime": "aider",
            },
            "ttl": 10,
        }
        if self.service_name == "composio":
            event["metadata"]["composio_connected"] = bool(self.composio_api_key)
            event["metadata"]["local_integrations"] = self.local_integrations.health() if self.local_integrations else []
        await self._publish_nats(self.nc, MESH_REGISTER, event, "agent.register")

    async def heartbeat_loop(self, max_runs: int = MAX_AGENT_HEARTBEATS):
        for _ in range(max(0, min(max_runs, MAX_AGENT_HEARTBEATS))):
            await asyncio.sleep(5)
            try:
                await self._publish_nats(
                    self.nc,
                    MESH_HEARTBEAT,
                    {
                        "service": self.service_name,
                        "instance_id": self.instance_id,
                        "load": self.request_count / 100.0,
                        "healthy": True,
                        "timestamp": utc_now_iso(),
                    },
                    "agent.heartbeat",
                )
                self.request_count = 0
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)

    async def subscribe_calls(
        self,
        max_messages: int = MAX_AGENT_MESSAGES,
        idle_timeout_seconds: float = MAX_AGENT_SUBSCRIBE_IDLE_SECONDS,
    ):
        try:
            sub = await self.nc.subscribe(call_subscribe_subject(self.service_name))
            processed = 0
            bounded_messages = max(0, min(max_messages, MAX_AGENT_MESSAGES))
            bounded_idle = max(0.001, min(idle_timeout_seconds, MAX_AGENT_SUBSCRIBE_IDLE_SECONDS))
            while processed < bounded_messages:
                try:
                    msg = await asyncio.wait_for(sub.messages.__anext__(), timeout=bounded_idle)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                try:
                    capability = parse_capability_from_subject(msg.subject)
                    payload = self.contracts.materialize_payload(
                        "runtime.capability.call_message",
                        json.loads(msg.data.decode()),
                    )
                    request_id = payload.get("request_id", str(uuid.uuid4())[:12])
                    params = payload.get("params", {})
                    result = await self.handle_capability(capability, params)
                    await self._publish_nats(self.js, reply_subject(request_id), result, "agent.reply")
                    self.request_count += 1
                    processed += 1
                except Exception as exc:
                    logger.error("Error processing call: %s", exc)
        except NATSError as exc:
            logger.error("Subscription error: %s", exc)

    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self.audit.execute(self.dispatch, capability, params)

    async def local_integration(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.local_integrations is None:
            return {
                "status": "error",
                "capability": capability,
                "error_code": "LOCAL_INTEGRATIONS_UNAVAILABLE",
                "reason": "local integration registry is not available",
                "context": {},
                "recoverable": True,
            }
        return self.local_integrations.execute(capability, params)

    async def analyze_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        source = sanitize_string(params.get("source", ""), 100_000)
        language = sanitize_string(params.get("language", "python"), 32)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.analyze",
            "language": language,
            "analysis": {
                "lines": len(source.split("\n")),
                "chars": len(source),
            },
            "timestamp": utc_now_iso(),
        }

    async def transform_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        source = sanitize_string(params.get("source", ""), 100_000)
        transform_type = sanitize_string(params.get("type", "refactor"), 64)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.transform",
            "type": transform_type,
            "output": source,
            "timestamp": utc_now_iso(),
        }

    async def generate_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = sanitize_string(params.get("spec", ""), 8192)
        language = sanitize_string(params.get("language", "python"), 32)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.generate",
            "language": language,
            "spec": spec,
            "timestamp": utc_now_iso(),
        }

    async def plan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        goal = sanitize_string(params.get("goal", ""), 512)
        plan = self.planner.plan(goal)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.plan",
            "goal": goal,
            "plan": plan.as_dict(),
            "planner_only": True,
            "timestamp": utc_now_iso(),
        }

    async def decompose(self, params: Dict[str, Any]) -> Dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        plan = self.planner.decompose(problem)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.decompose",
            "problem": problem,
            "subtasks": [step["id"] for step in plan.as_dict()["steps"]],
            "plan": plan.as_dict(),
            "planner_only": True,
            "timestamp": utc_now_iso(),
        }

    async def check_anomaly(self, metric: str, value: float) -> bool:
        history = self.metric_history.get(metric, [])
        try:
            return zscore_anomaly(history, value, max_samples=self._max_metric_history)
        except Exception:
            return False

    async def detect_anomaly(self, params: Dict[str, Any]) -> Dict[str, Any]:
        metric = sanitize_string(params.get("metric", "unknown"), 128)
        value = float(params.get("value", 0))
        is_anomaly = await self.check_anomaly(metric, value)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "anomaly.detect",
            "metric": metric,
            "value": value,
            "is_anomaly": is_anomaly,
            "severity": "high" if is_anomaly else "normal",
            "timestamp": utc_now_iso(),
        }

    async def ingest_metric(self, params: Dict[str, Any]) -> Dict[str, Any]:
        metric = sanitize_string(params.get("name", "unknown"), 128)
        value = float(params.get("value", 0))
        self.metric_history.setdefault(metric, []).append(value)
        self.metric_history[metric] = self.metric_history[metric][-self._max_metric_history :]
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "metrics.ingest",
            "metric": metric,
            "samples": len(self.metric_history[metric]),
            "timestamp": utc_now_iso(),
        }

    async def compute_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        metrics = params.get("metrics", {})
        anomalies = 0
        for metric, value in metrics.items():
            if await self.check_anomaly(sanitize_string(metric, 128), float(value)):
                anomalies += 1
        health_score = max(0, 100 - anomalies * 20)
        status = "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "critical"
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "system.health",
            "health_score": health_score,
            "status": status,
            "anomalies": anomalies,
            "timestamp": utc_now_iso(),
        }

    async def compute_ashi(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        anomalies = 0
        for metric, values in self.metric_history.items():
            if values and await self.check_anomaly(metric, values[-1]):
                anomalies += 1
        self.ashi_score = max(0, 100 - anomalies * 15)
        level = "optimal" if self.ashi_score >= 90 else "good" if self.ashi_score >= 70 else "fair" if self.ashi_score >= 50 else "critical"
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "ashi.compute",
            "ashi_score": self.ashi_score,
            "level": level,
            "timestamp": utc_now_iso(),
        }

    async def send_email(self, params: Dict[str, Any]) -> Dict[str, Any]:
        to = sanitize_string(params.get("to", ""), 256)
        subject = sanitize_string(params.get("subject", ""), 256)
        body = sanitize_string(params.get("body", ""), 10_000)
        context = {"to": to, "subject": subject, "body_length": len(body)}
        return self._local_action_unavailable("external.email", context)

    async def github_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        repo = sanitize_string(params.get("repo", ""), 256)
        return self._local_action_unavailable("external.github", {"action": action, "repo": repo})

    async def slack_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        channel = sanitize_string(params.get("channel", ""), 128)
        message = sanitize_string(params.get("message", ""), 4000)
        return self._local_action_unavailable("external.slack", {"channel": channel, "message_length": len(message)})

    async def notion_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        database = sanitize_string(params.get("database", ""), 256)
        return self._local_action_unavailable("external.notion", {"action": action, "database": database})

    async def calendar_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        return self._local_action_unavailable("external.calendar", {"action": action})

    async def crm_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        entity = sanitize_string(params.get("entity", ""), 128)
        return self._local_action_unavailable("external.crm", {"action": action, "entity": entity})

    def _is_local_integration(self, capability: str) -> bool:
        return bool(self.local_integrations and capability in self.local_integrations.capabilities())

    def _local_integrations_ready(self) -> bool:
        return bool(self.local_integrations and self.local_integrations.capabilities())

    def _local_action_unavailable(self, capability: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "error",
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": capability,
            "error_code": "ARK_LOCAL_CONNECTOR_NOT_IMPLEMENTED",
            "reason": "No ARK-made local connector is registered for this action yet",
            "context": context,
            "recoverable": True,
            "timestamp": utc_now_iso(),
        }

    def _with_result_record(self, capability: str, result: Dict[str, Any]) -> Dict[str, Any]:
        bus_result = self._publish_capability("agent.capability.result", capability, summarize_result(result))
        return bus_result or result

    def _publish_capability(
        self,
        action: str,
        capability: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        return self.audit.record(action, capability, payload)

    async def _publish_nats(self, target: Any, subject: str, payload: Dict[str, Any], capability: str) -> None:
        bus_result = await self.audit.publish_json(target, subject, payload, capability)
        if bus_result:
            return

    def _gsb_source(self) -> str:
        sources = {
            "opencode": EventSource.AGENT_OPENCODE.value,
            "openwolf": EventSource.AGENT_OPENWOLF.value,
            "composio": EventSource.AGENT_COMPOSIO.value,
        }
        return sources.get(self.service_name, EventSource.ARK_CORE.value)

    def _build_dispatch_descriptors(self) -> tuple[DispatchDescriptor, ...]:
        descriptors = [
            DispatchDescriptor("code.analyze", self.analyze_code),
            DispatchDescriptor("code.transform", self.transform_code),
            DispatchDescriptor("code.generate", self.generate_code),
            DispatchDescriptor("reasoning.plan", self.plan),
            DispatchDescriptor("reasoning.decompose", self.decompose),
            DispatchDescriptor("anomaly.detect", self.detect_anomaly),
            DispatchDescriptor("system.health", self.compute_health),
            DispatchDescriptor("metrics.ingest", self.ingest_metric),
            DispatchDescriptor("ashi.compute", self.compute_ashi),
            DispatchDescriptor("external.email", self.send_email),
            DispatchDescriptor("external.github", self.github_action),
            DispatchDescriptor("external.slack", self.slack_message),
            DispatchDescriptor("external.notion", self.notion_action),
            DispatchDescriptor("external.calendar", self.calendar_action),
            DispatchDescriptor("external.crm", self.crm_action),
        ]
        if self.local_integrations is not None:
            for capability in self.local_integrations.capabilities():
                descriptors.append(DispatchDescriptor(capability, self._local_dispatch_for(capability)))
        return tuple(descriptors)

    def _local_dispatch_for(self, capability: str):
        async def _dispatch(params: Dict[str, Any]) -> Dict[str, Any]:
            if not isinstance(params, dict):
                return runtime_failure("LOCAL_INTEGRATION_PARAMS_INVALID", "local integration params must be an object")
            return await self.local_integration(capability, params)

        return _dispatch
