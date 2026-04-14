#!/usr/bin/env python3
"""
ARK Autoscaler - Spawns services on demand based on event pressure
Monitors queue depth, latency, and capability demand
"""

import asyncio
import hmac
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime
from typing import Dict, List, Any

import nats
from nats.errors import Error as NATSError

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
        self.nc = None
        self.js = None
        
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
        """Connect to NATS"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            logger.info(f"Connected to NATS at {self.nats_url}")
        except NATSError as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise
    
    async def monitor_demand(self):
        """Listen for demand signals"""
        try:
            sub = await self.nc.subscribe("ark.system.queue_depth.*")
            logger.info("Subscribed to demand signals")
            
            async for msg in sub.messages:
                try:
                    subject_parts = msg.subject.split('.')
                    service = subject_parts[-1] if len(subject_parts) > 3 else "unknown"
                    
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
            sub = await self.nc.subscribe("ark.system.latency.*")
            
            async for msg in sub.messages:
                try:
                    subject_parts = msg.subject.split('.')
                    service = subject_parts[-1] if len(subject_parts) > 3 else "unknown"
                    
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
        """Spawn a new service instance"""
        if service not in self.spawn_config:
            logger.error(f"Unknown service: {service}")
            return ""
        
        config = self.spawn_config[service]
        instance_id = str(uuid.uuid4())[:12]
        container_name = f"ark-{service}-{instance_id}"
        
        try:
            # Build docker run command
            cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                f"--cpus={config['cpu_limit']}",
                f"--memory={config['memory_limit']}",
                "-e", f"INSTANCE_ID={instance_id}",
                "-e", f"SERVICE_NAME={service}",
                "-e", f"NATS_URL={self.nats_url}",
                "--network", "ark-net",
                config['image']
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                container_id = result.stdout.strip()
                
                if service not in self.service_instances:
                    self.service_instances[service] = []
                
                self.service_instances[service].append(container_id)
                
                logger.info(f"Spawned {service}/{instance_id}: {container_id}")
                
                # Publish spawn event
                await self.js.publish("ark.spawn.confirmed", json.dumps({
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
        """Terminate an idle service instance"""
        instances = self.service_instances.get(service, [])
        if not instances:
            return
        
        container_id = instances.pop()
        
        try:
            cmd = ["docker", "stop", container_id]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info(f"Terminated {service}: {container_id}")
                
                # Also remove container
                subprocess.run(["docker", "rm", container_id], timeout=5)
        
        except Exception as e:
            logger.error(f"Termination error for {service}: {e}")
    
    async def monitor_ashi(self):
        """Listen for ASHI (System Health Index) degradation signals"""
        try:
            sub = await self.nc.subscribe("ark.system.ashi")
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
        """Expose REST API for autoscaler control"""
        from aiohttp import web

        @web.middleware
        async def auth_middleware(request, handler):
            """Require API key for mutating endpoints"""
            if request.method in ('POST', 'PUT', 'DELETE'):
                api_key = os.environ.get('AUTOSCALER_API_KEY', '')
                if not api_key:
                    return web.json_response(
                        {"error": "AUTOSCALER_API_KEY not configured on server"},
                        status=503
                    )
                provided = request.headers.get('X-API-Key', '')
                if not provided or not hmac.compare_digest(provided, api_key):
                    return web.json_response({"error": "Unauthorized"}, status=401)
            return await handler(request)

        async def get_instances_handler(request):
            service = request.match_info.get('service', '')
            instances = self.service_instances.get(service, [])
            return web.json_response({
                "service": service,
                "instances": instances,
                "count": len(instances)
            })
        
        async def spawn_handler(request):
            data = await request.json()
            service = data.get('service', '')
            if service not in self.spawn_config:
                return web.json_response(
                    {"error": f"Unknown service: {service}"},
                    status=400
                )
            container_id = await self.spawn_instance(service)
            return web.json_response({
                "service": service,
                "container_id": container_id,
                "success": bool(container_id)
            })
        
        app = web.Application(middlewares=[auth_middleware])
        app.router.add_get('/api/instances/{service}', get_instances_handler)
        app.router.add_post('/api/spawn', spawn_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Autoscaler API listening on {host}:{port}")
    
    async def run(self):
        """Main autoscaler loop"""
        try:
            await self.connect()
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
            if self.nc:
                await self.nc.close()


async def main():
    autoscaler = Autoscaler()
    await autoscaler.run()


if __name__ == "__main__":
    asyncio.run(main())
