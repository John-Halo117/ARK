#!/usr/bin/env python3
"""
ARK Autoscaler - Spawns services on demand based on event pressure
Monitors queue depth, latency, and capability demand
"""

import asyncio
import json
import logging
import subprocess
import uuid
from datetime import datetime
from typing import Dict, List, Any

import nats
from nats.errors import Error as NATSError

from ark.security import (
    build_safe_docker_cmd,
    sanitize_string,
    validate_docker_arg,
    validate_service_name,
)
from ark.maintenance import (
    HealthCheck,
    ResilientNATSConnection,
    ShutdownCoordinator,
)
from ark.subjects import (
    SYSTEM_QUEUE_DEPTH_SUBSCRIBE, SYSTEM_LATENCY_SUBSCRIBE,
    SYSTEM_ASHI, SPAWN_CONFIRMED,
    parse_service_from_queue_depth,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ARK-Autoscaler')


class Autoscaler:
    """Dynamic compute spawner based on demand signals"""
    
    def __init__(self, nats_url: str = "nats://nats:4222", 
                 docker_sock: str = "/var/run/docker.sock"):
        self.nats_url = nats_url
        self.docker_sock = docker_sock
        self._nats = ResilientNATSConnection(nats_url)
        self.nc = None
        self.js = None
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck("ark-autoscaler")
        self.health.register("nats", lambda: self._nats.is_connected)
        
        # Spawn config
        self.spawn_config = {
            "opencode": {
                "image": "ark-opencode:latest",
                "cpu_limit": "1",
                "memory_limit": "1G",
                "min_instances": 1,
                "max_instances": 5,
                "queue_threshold": 10,
                "latency_threshold": 1000  # ms
            },
            "openwolf": {
                "image": "ark-openwolf:latest",
                "cpu_limit": "0.5",
                "memory_limit": "512M",
                "min_instances": 1,
                "max_instances": 3,
                "queue_threshold": 20,
                "latency_threshold": 500
            },
            "composio": {
                "image": "ark-composio:latest",
                "cpu_limit": "1",
                "memory_limit": "1G",
                "min_instances": 1,
                "max_instances": 10,
                "queue_threshold": 50,
                "latency_threshold": 2000
            }
        }
        
        # Service state
        self.service_instances: Dict[str, List[str]] = {}
        self.service_demand: Dict[str, float] = {}
        self.service_latency: Dict[str, float] = {}
        
        logger.info("ARK Autoscaler initialized")
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        logger.info("Connected to NATS at %s", self.nats_url)
    
    async def monitor_demand(self):
        """Listen for demand signals"""
        try:
            sub = await self.nc.subscribe(SYSTEM_QUEUE_DEPTH_SUBSCRIBE)
            logger.info("Subscribed to demand signals")
            
            async for msg in sub.messages:
                try:
                    service = parse_service_from_queue_depth(msg.subject)
                    
                    event = json.loads(msg.data.decode())
                    depth = event.get('depth', 0)
                    
                    self.service_demand[service] = depth
                    
                    # Check if scaling needed
                    await self.check_scaling(service)
                
                except Exception as e:
                    logger.error(f"Error processing demand signal: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def monitor_latency(self):
        """Listen for latency signals"""
        try:
            sub = await self.nc.subscribe(SYSTEM_LATENCY_SUBSCRIBE)
            
            async for msg in sub.messages:
                try:
                    service = parse_service_from_queue_depth(msg.subject)
                    
                    event = json.loads(msg.data.decode())
                    latency = event.get('latency_ms', 0)
                    
                    self.service_latency[service] = latency
                
                except Exception as e:
                    logger.error(f"Error processing latency signal: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def check_scaling(self, service: str):
        """Check if service needs scaling"""
        if service not in self.spawn_config:
            return
        
        config = self.spawn_config[service]
        demand = self.service_demand.get(service, 0)
        latency = self.service_latency.get(service, 0)
        instance_count = len(self.service_instances.get(service, []))
        
        # Scale up if demand high
        if demand > config['queue_threshold'] and instance_count < config['max_instances']:
            logger.info(f"Scaling up {service}: demand={demand}, instances={instance_count}")
            await self.spawn_instance(service)
        
        # Scale up if latency high
        elif latency > config['latency_threshold'] and instance_count < config['max_instances']:
            logger.info(f"Scaling up {service}: latency={latency}ms, instances={instance_count}")
            await self.spawn_instance(service)
        
        # Scale down if idle
        elif demand == 0 and instance_count > config['min_instances']:
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
                
                if service not in self.service_instances:
                    self.service_instances[service] = []
                
                self.service_instances[service].append(container_id)
                
                logger.info(f"Spawned {service}/{instance_id}: {container_id}")
                
                # Publish spawn event
                await self.js.publish(SPAWN_CONFIRMED, json.dumps({
                    "service": service,
                    "instance_id": instance_id,
                    "container_id": container_id,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
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
        
        container_id = instances.pop()
        
        try:
            # Validate container_id to prevent injection
            validate_docker_arg(container_id)
            cmd = ["docker", "stop", container_id]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info("Terminated %s: %s", service, container_id)
                subprocess.run(
                    ["docker", "rm", container_id],
                    capture_output=True, text=True, timeout=5,
                )
        
        except Exception as e:
            logger.error(f"Termination error for {service}: {e}")
    
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
