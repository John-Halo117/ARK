#!/usr/bin/env python3
"""
ARK Autoscaler - Spawns services on demand based on event pressure
Monitors queue depth, latency, and capability demand
"""

import asyncio
import json
import logging
from pathlib import Path
import subprocess
import uuid
from typing import Dict, List

try:
    from nats.errors import Error as NATSError
except ImportError:  # pragma: no cover - local import/test environments
    NATSError = RuntimeError

from ark.security import (
    build_safe_docker_cmd,
    validate_docker_arg,
    validate_service_name,
)
from ark.maintenance import (
    HealthCheck,
    ResilientNATSConnection,
    ShutdownCoordinator,
)
from ark.event_schema import EventSource
from ark.gsb import GlobalStateBus, build_global_state_bus
from ark.subjects import (
    SYSTEM_QUEUE_DEPTH_SUBSCRIBE, SYSTEM_LATENCY_SUBSCRIBE,
    SYSTEM_ASHI, SPAWN_CONFIRMED,
    parse_service_from_system_subject,
)
from ark.policy_engine import load_policy_set
from ark.reducers import AutoscalerViewReducer, ReducerEngine
from ark.runtime_contracts import runtime_contract_registry
from ark.runtime_flow import RuntimeAudit
from ark.time_utils import utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ARK-Autoscaler')


class Autoscaler:
    """Dynamic compute spawner based on demand signals"""
    
    def __init__(self, nats_url: str = "nats://nats:4222", 
                 docker_sock: str = "/var/run/docker.sock",
                 gsb: GlobalStateBus | None = None):
        self.nats_url = nats_url
        self.docker_sock = docker_sock
        self._nats = ResilientNATSConnection(nats_url)
        self.nc = None
        self.js = None
        self.gsb = gsb or build_global_state_bus()
        self.audit = RuntimeAudit(
            self.gsb,
            source=EventSource.ARK_CORE.value,
            surface="autoscaler",
            default_tags={"surface": "autoscaler"},
        )
        self.contracts = runtime_contract_registry()
        self.scaling_policy = load_policy_set(Path(__file__).resolve().parents[1] / "policy" / "autoscaler_rules.json")
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck("ark-autoscaler")
        self.health.register("nats", lambda: self._nats.is_connected)
        self.health.register("gsb", lambda: self.gsb.health()["enabled"])
        self.reducer_engine = ReducerEngine((AutoscalerViewReducer(),))
        self.health.register("reducers", lambda: self.reducer_engine.health()["healthy"])
        
        # Spawn config
        self.spawn_config = dict(self.scaling_policy.extras.get("services", {}))
        
        # Service state
        autoscaler_view = self.reducer_engine.view("autoscaler.runtime")
        self.service_instances: Dict[str, List[str]] = autoscaler_view["instances"]
        self.service_demand: Dict[str, float] = autoscaler_view["demand"]
        self.service_latency: Dict[str, float] = autoscaler_view["latency"]
        
        logger.info("ARK Autoscaler initialized")
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        logger.info("Connected to NATS at %s", self.nats_url)
    
    async def monitor_demand(self):
        """Listen for demand signals"""
        await self._monitor_system_signal(
            pattern=SYSTEM_QUEUE_DEPTH_SUBSCRIBE,
            signal_name="queue_depth",
            callback=self._on_queue_depth_signal,
            subscription_label="demand signals",
        )
    
    async def monitor_latency(self):
        """Listen for latency signals"""
        await self._monitor_system_signal(
            pattern=SYSTEM_LATENCY_SUBSCRIBE,
            signal_name="latency",
            callback=self._on_latency_signal,
            subscription_label="latency signals",
        )

    async def _monitor_system_signal(self, pattern: str, signal_name: str, callback, subscription_label: str):
        """Shared pub/sub monitor for ark.system.* subjects."""
        try:
            sub = await self.nc.subscribe(pattern)
            logger.info("Subscribed to %s", subscription_label)

            async for msg in sub.messages:
                try:
                    service = parse_service_from_system_subject(msg.subject, expected_signal=signal_name)
                    if service == "unknown":
                        logger.warning("Ignoring malformed subject: %s", msg.subject)
                        continue
                    event = json.loads(msg.data.decode())
                    if not isinstance(event, dict):
                        logger.warning("Ignoring malformed payload for %s: %r", msg.subject, event)
                        continue
                    await callback(service, event)
                except json.JSONDecodeError:
                    logger.warning("Ignoring invalid JSON payload for subject: %s", msg.subject)
                except Exception as e:
                    logger.error("Error processing %s signal: %s", signal_name, e)

        except NATSError as e:
            logger.error("Subscription error on %s: %s", pattern, e)

    async def _on_queue_depth_signal(self, service: str, event: dict):
        """Handle queue depth signal and trigger scaling decisions."""
        depth = event.get('depth', 0)
        if not isinstance(depth, (int, float)) or depth < 0:
            logger.warning("Ignoring invalid depth for %s: %r", service, depth)
            return
        self.service_demand[service] = float(depth)
        await self.check_scaling(service)

    async def _on_latency_signal(self, service: str, event: dict):
        """Handle latency signal."""
        latency = event.get('latency_ms', 0)
        if not isinstance(latency, (int, float)) or latency < 0:
            logger.warning("Ignoring invalid latency for %s: %r", service, latency)
            return
        self.service_latency[service] = float(latency)
    
    async def check_scaling(self, service: str):
        """Check if service needs scaling"""
        if service not in self.spawn_config:
            return
        
        config = self.spawn_config[service]
        demand = self.service_demand.get(service, 0)
        latency = self.service_latency.get(service, 0)
        instance_count = len(self.service_instances.get(service, []))
        
        decision = self.scaling_policy.evaluate(
            {
                "service": service,
                "demand": demand,
                "latency": latency,
                "instance_count": instance_count,
                "queue_threshold": config['queue_threshold'],
                "latency_threshold": config['latency_threshold'],
                "min_instances": config['min_instances'],
                "max_instances": config['max_instances'],
            }
        )
        self.reducer_engine.apply(
            "autoscaler.decision",
            {"service": service, "decision": decision.decision},
        )
        self.audit.record(
            "decision",
            "autoscaler.scale",
            {"service": service, "decision": decision.decision, "rule": decision.rule_name},
        )

        if decision.decision == "scale_up":
            logger.info(f"Scaling up {service}: demand={demand}, latency={latency}, instances={instance_count}")
            await self.spawn_instance(service)
        elif decision.decision == "scale_down":
            logger.info(f"Scaling down {service}: idle, instances={instance_count}")
            await self.terminate_instance(service)
    
    async def spawn_instance(self, service: str) -> str:
        """Spawn a new service instance with hardened docker invocation"""
        try:
            validate_service_name(service)
        except ValueError:
            logger.error("Invalid service name: %s", service)
            return ""
        if service not in self.spawn_config:
            logger.error("Unknown service: %s", service)
            return ""
        
        config = self.spawn_config[service]
        instance_id = str(uuid.uuid4())[:12]
        container_name = f"ark-{service}-{instance_id}"
        if self.audit.record("spawn.request", "autoscaler.spawn.request", {"service": service}):
            return ""
        
        try:
            cmd = build_safe_docker_cmd(
                image=config['image'],
                container_name=container_name,
                cpu_limit=config['cpu_limit'],
                memory_limit=config['memory_limit'],
                env={
                    "INSTANCE_ID": instance_id,
                    "SERVICE_NAME": service,
                    "NATS_URL": self.nats_url,
                },
                network="ark-net",
            )
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                container_id = result.stdout.strip()
                
                self.reducer_engine.apply(
                    "autoscaler.instance_spawned",
                    {"service": service, "container_id": container_id},
                )
                
                logger.info(f"Spawned {service}/{instance_id}: {container_id}")
                
                # Publish spawn event
                await self._publish_nats(self.js, SPAWN_CONFIRMED, {
                    "service": service,
                    "instance_id": instance_id,
                    "container_id": container_id,
                    "timestamp": utc_now_iso()
                }, "autoscaler.spawn.confirmed")
                
                return container_id
            else:
                logger.error(f"Failed to spawn {service}: {result.stderr}")
                return ""
        
        except Exception as e:
            logger.error(f"Spawn error for {service}: {e}")
            return ""
    
    async def terminate_instance(self, service: str):
        """Terminate an idle service instance safely"""
        instances = self.service_instances.get(service, [])
        if not instances:
            return
        
        container_id = instances[-1]
        
        try:
            # Validate container_id to prevent injection
            validate_docker_arg(container_id)
            cmd = ["docker", "stop", container_id]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info("Terminated %s: %s", service, container_id)
                self.reducer_engine.apply(
                    "autoscaler.instance_terminated",
                    {"service": service, "container_id": container_id},
                )
                subprocess.run(
                    ["docker", "rm", container_id],
                    capture_output=True, text=True, timeout=5,
                )
        
        except Exception as e:
            logger.error(f"Termination error for {service}: {e}")

    async def _publish_nats(self, target: object, subject: str, payload: Dict[str, object], capability: str) -> None:
        error = await self.audit.publish_json(target, subject, payload, capability)
        if error:
            return
    
    async def monitor_ashi(self):
        """Listen for ASHI (System Health Index) degradation signals"""
        try:
            sub = await self.nc.subscribe(SYSTEM_ASHI)
            logger.info("Subscribed to ASHI signals")
            
            async for msg in sub.messages:
                try:
                    event = json.loads(msg.data.decode())
                    ashi_score = event.get('score', 100)
                    
                    # If health degrading, may need to spawn recovery instances
                    if ashi_score < 60:
                        logger.warning(f"ASHI degraded: {ashi_score}")
                        # Could trigger recovery spawns here
                
                except Exception as e:
                    logger.error(f"Error processing ASHI signal: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def expose_api(self, host: str = "0.0.0.0", port: int = 7001):
        """Expose REST API for autoscaler control with auth"""
        from aiohttp import web
        from ark.security import (
            auth_middleware,
            error_shield_middleware,
            rate_limit_middleware,
            secure_headers_middleware,
        )
        
        async def get_health_handler(request):
            return web.json_response(self.health.check())

        async def get_instances_handler(request):
            service = request.match_info.get('service', '')
            try:
                validate_service_name(service)
            except ValueError:
                return web.json_response({"error": "invalid service name"}, status=400)
            instances = self.service_instances.get(service, [])
            return web.json_response({
                "service": service,
                "instances": instances,
                "count": len(instances)
            })
        
        async def spawn_handler(request):
            data = await request.json()
            service = data.get('service', '')
            try:
                validate_service_name(service)
            except ValueError:
                return web.json_response({"error": "invalid service name"}, status=400)
            container_id = await self.spawn_instance(service)
            return web.json_response({
                "service": service,
                "container_id": container_id,
                "success": bool(container_id)
            })
        
        app = web.Application(
            middlewares=[
                error_shield_middleware,
                secure_headers_middleware,
                rate_limit_middleware,
                auth_middleware,
            ]
        )
        app.router.add_get('/api/health', get_health_handler)
        app.router.add_get('/api/instances/{service}', get_instances_handler)
        app.router.add_post('/api/spawn', spawn_handler)
        
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        logger.info(f"Autoscaler API listening on {host}:{port}")
    
    async def run(self):
        """Main autoscaler loop with graceful shutdown"""
        try:
            self.shutdown.install_signal_handlers()
            await self._nats.connect()
            self.nc = self._nats.nc
            self.js = self._nats.js
            await self.expose_api()
            
            logger.info("ARK Autoscaler started")
            
            await asyncio.gather(
                self.monitor_demand(),
                self.monitor_latency(),
                self.monitor_ashi()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if hasattr(self, '_runner') and self._runner:
                await self._runner.cleanup()
            await self._nats.close()
            logger.info("Autoscaler shutdown complete")


async def main():
    autoscaler = Autoscaler()
    await autoscaler.run()


if __name__ == "__main__":
    asyncio.run(main())
