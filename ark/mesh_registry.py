#!/usr/bin/env python3
"""
ARK Mesh Registry - Service discovery via capability graph
Manages dynamic service registration, health, and routing decisions
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import nats
from nats.errors import Error as NATSError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ARK-MeshRegistry')


class ServiceInstance:
    """Represents a registered service instance"""
    
    def __init__(self, service: str, instance_id: str, capabilities: List[str], 
                 metadata: Dict[str, Any] = None, ttl_seconds: int = 10):
        self.service = service
        self.instance_id = instance_id
        self.capabilities = capabilities
        self.metadata = metadata or {}
        self.ttl_seconds = ttl_seconds
        self.registered_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.load = 0.0
        self.healthy = True
    
    def is_expired(self) -> bool:
        """Check if heartbeat has expired"""
        elapsed = (datetime.utcnow() - self.last_heartbeat).total_seconds()
        return elapsed > self.ttl_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict"""
        return {
            "service": self.service,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "load": self.load,
            "healthy": self.healthy,
            "registered_at": self.registered_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "metadata": self.metadata
        }


class MeshRegistry:
    """Central service registry and capability router"""
    
    def __init__(self, nats_url: str = "nats://nats:4222"):
        self.nats_url = nats_url
        self.nc = None
        self.js = None
        
        # Registry: service -> instance_id -> ServiceInstance
        self.registry: Dict[str, Dict[str, ServiceInstance]] = {}
        
        # Capability index: capability -> [instance_ids]
        self.capability_index: Dict[str, List[str]] = {}
        
        # Active subscriptions
        self.subscriptions = {}
        
        logger.info("ARK Mesh Registry initialized")
    
    async def connect(self):
        """Connect to NATS"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            logger.info(f"Connected to NATS at {self.nats_url}")
        except NATSError as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise
    
    async def subscribe_registrations(self):
        """Listen for service registrations"""
        try:
            sub = await self.nc.subscribe("ark.mesh.register")
            logger.info("Subscribed to ark.mesh.register")
            
            async for msg in sub.messages:
                try:
                    event = json.loads(msg.data.decode())
                    await self.handle_registration(event)
                except Exception as e:
                    logger.error(f"Error processing registration: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_registration(self, event: Dict[str, Any]):
        """Register or update a service instance"""
        service = event.get('service')
        instance_id = event.get('instance_id')
        capabilities = event.get('capabilities', [])
        ttl = event.get('ttl', 10)
        metadata = event.get('metadata', {})
        
        if not service or not instance_id:
            logger.warning(f"Invalid registration: {event}")
            return
        
        # Store instance
        if service not in self.registry:
            self.registry[service] = {}
        
        self.registry[service][instance_id] = ServiceInstance(
            service, instance_id, capabilities, metadata, ttl
        )
        
        # Update capability index
        for capability in capabilities:
            if capability not in self.capability_index:
                self.capability_index[capability] = []
            if instance_id not in self.capability_index[capability]:
                self.capability_index[capability].append(instance_id)
        
        logger.info(f"Registered {service}/{instance_id}: {capabilities}")
        
        # Publish registration event
        await self.js.publish("ark.mesh.registered", json.dumps({
            "service": service,
            "instance_id": instance_id,
            "capabilities": capabilities,
            "timestamp": datetime.utcnow().isoformat()
        }).encode())
    
    async def subscribe_heartbeats(self):
        """Listen for service heartbeats"""
        try:
            sub = await self.nc.subscribe("ark.mesh.heartbeat")
            logger.info("Subscribed to ark.mesh.heartbeat")
            
            async for msg in sub.messages:
                try:
                    event = json.loads(msg.data.decode())
                    service = event.get('service')
                    instance_id = event.get('instance_id')
                    load = event.get('load', 0.0)
                    
                    if service in self.registry and instance_id in self.registry[service]:
                        inst = self.registry[service][instance_id]
                        inst.last_heartbeat = datetime.utcnow()
                        inst.load = load
                        inst.healthy = event.get('healthy', True)
                        logger.debug(f"Heartbeat: {service}/{instance_id} load={load}")
                
                except Exception as e:
                    logger.error(f"Error processing heartbeat: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def cleanup_expired(self):
        """Periodically remove expired instances"""
        while True:
            await asyncio.sleep(5)
            
            expired = []
            for service, instances in self.registry.items():
                for instance_id, inst in list(instances.items()):
                    if inst.is_expired():
                        expired.append((service, instance_id))
                        del instances[instance_id]
                        logger.info(f"Removed expired: {service}/{instance_id}")
            
            # Clean capability index
            for capability in list(self.capability_index.keys()):
                self.capability_index[capability] = [
                    iid for iid in self.capability_index[capability]
                    if not any(iid in insts for insts in self.registry.values())
                ]
                if not self.capability_index[capability]:
                    del self.capability_index[capability]
    
    async def route_capability(self, capability: str, load_aware: bool = True) -> Optional[tuple]:
        """Route a capability request to best instance"""
        if capability not in self.capability_index:
            return None
        
        candidates = self.capability_index[capability]
        if not candidates:
            return None
        
        # Find service and instance
        best_instance = None
        best_load = float('inf')
        best_service = None
        
        for service, instances in self.registry.items():
            for instance_id in candidates:
                if instance_id in instances:
                    inst = instances[instance_id]
                    if inst.healthy and load_aware:
                        if inst.load < best_load:
                            best_load = inst.load
                            best_instance = instance_id
                            best_service = service
                    elif inst.healthy:
                        return (service, instance_id)
        
        return (best_service, best_instance) if best_instance else None
    
    async def get_service_info(self, service: str) -> Dict[str, Any]:
        """Get service inventory"""
        if service not in self.registry:
            return {"service": service, "instances": []}
        
        instances = [
            inst.to_dict() 
            for inst in self.registry[service].values()
        ]
        
        return {
            "service": service,
            "instance_count": len(instances),
            "total_load": sum(inst['load'] for inst in instances),
            "instances": instances
        }
    
    async def get_mesh_status(self) -> Dict[str, Any]:
        """Get overall mesh status"""
        service_count = len(self.registry)
        instance_count = sum(len(insts) for insts in self.registry.values())
        capability_count = len(self.capability_index)
        
        services = {}
        for service in self.registry:
            insts = self.registry[service]
            services[service] = {
                "instance_count": len(insts),
                "total_load": sum(inst.load for inst in insts.values()),
                "healthy_count": sum(1 for inst in insts.values() if inst.healthy)
            }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "services": service_count,
            "instances": instance_count,
            "capabilities": capability_count,
            "service_details": services
        }
    
    async def expose_api(self, host: str = "0.0.0.0", port: int = 7000):
        """Expose REST API for mesh queries"""
        from aiohttp import web
        
        async def get_mesh_status_handler(request):
            status = await self.get_mesh_status()
            return web.json_response(status)
        
        async def get_service_handler(request):
            service = request.match_info.get('service', '')
            info = await self.get_service_info(service)
            return web.json_response(info)
        
        async def route_capability_handler(request):
            capability = request.match_info.get('capability', '')
            route = await self.route_capability(capability)
            if route:
                return web.json_response({
                    "capability": capability,
                    "service": route[0],
                    "instance_id": route[1]
                })
            return web.json_response({"error": "No instances available"}, status=404)
        
        app = web.Application()
        app.router.add_get('/api/mesh', get_mesh_status_handler)
        app.router.add_get('/api/service/{service}', get_service_handler)
        app.router.add_get('/api/route/{capability}', route_capability_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Mesh API listening on {host}:{port}")
    
    async def run(self):
        """Main registry loop"""
        try:
            await self.connect()
            await self.expose_api()
            
            logger.info("ARK Mesh Registry started")
            
            await asyncio.gather(
                self.subscribe_registrations(),
                self.subscribe_heartbeats(),
                self.cleanup_expired()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.nc:
                await self.nc.close()


async def main():
    registry = MeshRegistry()
    await registry.run()


if __name__ == "__main__":
    asyncio.run(main())
