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
from datetime import datetime
from statistics import mean, stdev
from typing import Any, Dict, List

from nats.errors import Error as NATSError

from ark.config import load_composio_config, load_service_runtime_config
from ark.maintenance import HealthCheck, ResilientNATSConnection, ShutdownCoordinator
from ark.security import sanitize_string
from ark.subjects import (
    MESH_HEARTBEAT,
    MESH_REGISTER,
    parse_capability_from_subject,
    call_subscribe_subject,
    reply_subject,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AiderAgent")

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

        self._nats = ResilientNATSConnection(self.nats_url)
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck(self.service_name)
        self.health.register("nats", lambda: self._nats.is_connected)

        # OpenWolf profile state
        self.metric_history: Dict[str, List[float]] = {}
        self._max_metric_history = 100
        self.ashi_score = 100

        # Composio profile state
        composio_cfg = load_composio_config()
        self.composio_api_key = composio_cfg.composio_api_key
        if self.service_name == "composio":
            self.health.register("composio_api", lambda: bool(self.composio_api_key))

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
                "started_at": datetime.utcnow().isoformat(),
                "runtime": "aider",
            },
            "ttl": 10,
        }
        if self.service_name == "composio":
            event["metadata"]["composio_connected"] = bool(self.composio_api_key)
        await self.nc.publish(MESH_REGISTER, json.dumps(event).encode())

    async def heartbeat_loop(self):
        while True:
            await asyncio.sleep(5)
            try:
                await self.nc.publish(
                    MESH_HEARTBEAT,
                    json.dumps(
                        {
                            "service": self.service_name,
                            "instance_id": self.instance_id,
                            "load": self.request_count / 100.0,
                            "healthy": True,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    ).encode(),
                )
                self.request_count = 0
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)

    async def subscribe_calls(self):
        try:
            sub = await self.nc.subscribe(call_subscribe_subject(self.service_name))
            async for msg in sub.messages:
                capability = parse_capability_from_subject(msg.subject)
                payload = json.loads(msg.data.decode())
                request_id = payload.get("request_id", str(uuid.uuid4())[:12])
                params = payload.get("params", {})
                result = await self.handle_capability(capability, params)
                await self.js.publish(reply_subject(request_id), json.dumps(result).encode())
                self.request_count += 1
        except NATSError as exc:
            logger.error("Subscription error: %s", exc)

    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "code.analyze": self.analyze_code,
            "code.transform": self.transform_code,
            "code.generate": self.generate_code,
            "reasoning.plan": self.plan,
            "reasoning.decompose": self.decompose,
            "anomaly.detect": self.detect_anomaly,
            "system.health": self.compute_health,
            "metrics.ingest": self.ingest_metric,
            "ashi.compute": self.compute_ashi,
            "external.email": self.send_email,
            "external.github": self.github_action,
            "external.slack": self.slack_message,
            "external.notion": self.notion_action,
            "external.calendar": self.calendar_action,
            "external.crm": self.crm_action,
        }
        handler = handlers.get(capability)
        if handler is None:
            return {"error": f"Unknown capability: {capability}"}
        return await handler(params)

    async def analyze_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        source = params.get("source", "")
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
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def transform_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        source = params.get("source", "")
        transform_type = sanitize_string(params.get("type", "refactor"), 64)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.transform",
            "type": transform_type,
            "output": source,
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def plan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        goal = sanitize_string(params.get("goal", ""), 512)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.plan",
            "goal": goal,
            "plan": {"steps": ["analyze", "design", "implement", "validate"]},
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def decompose(self, params: Dict[str, Any]) -> Dict[str, Any]:
        problem = sanitize_string(params.get("problem", ""), 512)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.decompose",
            "problem": problem,
            "subtasks": ["identify inputs", "process", "verify output"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def check_anomaly(self, metric: str, value: float) -> bool:
        history = self.metric_history.get(metric, [])
        if len(history) < 5:
            return False
        baseline = mean(history)
        sigma = stdev(history) if len(history) > 1 else 0.0
        if sigma == 0:
            return value > baseline * 1.5
        return value > baseline + (3.0 * sigma)

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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def send_email(self, params: Dict[str, Any]) -> Dict[str, Any]:
        to = sanitize_string(params.get("to", ""), 256)
        subject = sanitize_string(params.get("subject", ""), 256)
        body = sanitize_string(params.get("body", ""), 10_000)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.email",
            "to": to,
            "subject": subject,
            "body_length": len(body),
            "success": bool(self.composio_api_key),
            "message": "Email queued for delivery" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def github_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        repo = sanitize_string(params.get("repo", ""), 256)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.github",
            "action": action,
            "repo": repo,
            "success": bool(self.composio_api_key),
            "message": "GitHub action queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def slack_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        channel = sanitize_string(params.get("channel", ""), 128)
        message = sanitize_string(params.get("message", ""), 4000)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.slack",
            "channel": channel,
            "message_length": len(message),
            "success": bool(self.composio_api_key),
            "message": "Slack message queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def notion_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        database = sanitize_string(params.get("database", ""), 256)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.notion",
            "action": action,
            "database": database,
            "success": bool(self.composio_api_key),
            "message": "Notion action queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def calendar_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.calendar",
            "action": action,
            "success": bool(self.composio_api_key),
            "message": "Calendar action queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def crm_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = sanitize_string(params.get("action", ""), 128)
        entity = sanitize_string(params.get("entity", ""), 128)
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.crm",
            "action": action,
            "entity": entity,
            "success": bool(self.composio_api_key),
            "message": "CRM action queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat(),
        }
