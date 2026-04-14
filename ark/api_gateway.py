#!/usr/bin/env python3
"""
ARK API Gateway - Unified entry point for system queries and operations
Routes to: Mesh, DuckDB, agents, storage
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

import nats
from aiohttp import web
from ark.duck_client import DuckClient
from ark.event_schema import create_event, EventType, EventSource


def _safe_int(value: str, default: int, min_val: int = 1, max_val: int = 1000) -> int:
    """Safely parse an integer query parameter with bounds."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return max(min_val, min(default, max_val))
    return max(min_val, min(n, max_val))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ARK-Gateway')


class ARKGateway:
    """API Gateway for ARK system"""
    
    def __init__(self):
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        self.mesh_url = os.environ.get('MESH_URL', 'http://ark-mesh:7000')
        self.nc = None
        self.js = None
        self.db = DuckClient()
        
        logger.info("ARK Gateway initialized")
    
    async def connect(self):
        """Connect to NATS"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            logger.info(f"Connected to NATS")
        except Exception as e:
            logger.error(f"NATS connection failed: {e}")
            raise
    
    async def handle_mesh_status(self, request: web.Request) -> web.Response:
        """GET /api/mesh - Get mesh registry status"""
        try:
            # Query mesh registry directly via HTTP
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mesh_url}/api/mesh") as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception as e:
            logger.error(f"Mesh query error: {e}")
            return web.json_response({"error": "Failed to query mesh registry"}, status=500)
    
    async def handle_service_info(self, request: web.Request) -> web.Response:
        """GET /api/service/{name} - Get service info"""
        service = request.match_info.get('name', '')
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mesh_url}/api/service/{service}") as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception as e:
            logger.error(f"Service info error: {e}")
            return web.json_response({"error": "Failed to query service info"}, status=500)
    
    async def handle_route_capability(self, request: web.Request) -> web.Response:
        """GET /api/route/{capability} - Get best instance for capability"""
        capability = request.match_info.get('capability', '')
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mesh_url}/api/route/{capability}") as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception as e:
            logger.error(f"Route capability error: {e}")
            return web.json_response({"error": "Failed to route capability"}, status=500)
    
    async def handle_call_capability(self, request: web.Request) -> web.Response:
        """POST /api/call/{capability} - Call a capability"""
        capability = request.match_info.get('capability', '')
        
        try:
            body = await request.json()
            request_id = body.get('request_id', '').strip() or None
            params = body.get('params', {})
            
            # Route capability
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mesh_url}/api/route/{capability}") as resp:
                    if resp.status != 200:
                        return web.json_response({"error": "No service available"}, status=404)
                    
                    route = await resp.json()
            
            service = route.get('service')
            instance_id = route.get('instance_id')
            
            if not service:
                return web.json_response({"error": "No route available"}, status=404)
            
            # Publish capability call
            call_msg = {
                "request_id": request_id or f"req-{instance_id}-{int(datetime.utcnow().timestamp())}",
                "service": service,
                "instance_id": instance_id,
                "capability": capability,
                "params": params
            }
            
            await self.nc.publish(
                f"ark.call.{service}.{capability}",
                json.dumps(call_msg).encode()
            )
            
            logger.info(f"Routed capability {capability} to {service}/{instance_id}")
            
            return web.json_response({
                "request_id": call_msg['request_id'],
                "service": service,
                "instance_id": instance_id,
                "capability": capability,
                "status": "queued"
            })
        
        except Exception as e:
            logger.error(f"Capability call error: {e}")
            return web.json_response({"error": "Failed to execute capability call"}, status=500)
    
    async def handle_query_events(self, request: web.Request) -> web.Response:
        """GET /api/events?source=X&type=Y&limit=Z - Query events"""
        try:
            source = request.rel_url.query.get('source')
            event_type = request.rel_url.query.get('type')
            limit = _safe_int(request.rel_url.query.get('limit', '100'), 100)
            
            events = self.db.query_events(source, event_type, limit)
            
            return web.json_response({
                "count": len(events),
                "events": events
            })
        except Exception as e:
            logger.error(f"Event query error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)
    
    async def handle_query_metrics(self, request: web.Request) -> web.Response:
        """GET /api/metrics/{source} - Get latest LKS metrics"""
        source = request.match_info.get('source', '')
        limit = _safe_int(request.rel_url.query.get('limit', '10'), 10)
        
        try:
            metrics = self.db.get_latest_lks(source, limit)
            return web.json_response({
                "source": source,
                "count": len(metrics),
                "metrics": metrics
            })
        except Exception as e:
            logger.error(f"Metrics query error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)
    
    async def handle_system_status(self, request: web.Request) -> web.Response:
        """GET /api/status - Overall system status"""
        try:
            # Mesh status
            import aiohttp
            mesh_data = None
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.mesh_url}/api/mesh") as resp:
                        mesh_data = await resp.json()
            except Exception as e:
                logger.warning(f"Failed to fetch mesh status: {e}")
            
            # DB status
            db_data = self.db.get_mesh_status()
            
            return web.json_response({
                "timestamp": datetime.utcnow().isoformat(),
                "mesh": mesh_data or {"error": "unavailable"},
                "database": db_data,
                "gateway": "healthy"
            })
        except Exception as e:
            logger.error(f"System status error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)
    
    def create_app(self) -> web.Application:
        """Create aiohttp application"""
        app = web.Application()
        
        # Mesh queries
        app.router.add_get('/api/mesh', self.handle_mesh_status)
        app.router.add_get('/api/service/{name}', self.handle_service_info)
        app.router.add_get('/api/route/{capability}', self.handle_route_capability)
        
        # Capability execution
        app.router.add_post('/api/call/{capability}', self.handle_call_capability)
        
        # Data queries
        app.router.add_get('/api/events', self.handle_query_events)
        app.router.add_get('/api/metrics/{source}', self.handle_query_metrics)
        
        # System
        app.router.add_get('/api/status', self.handle_system_status)
        
        return app
    
    async def run(self, host: str = "0.0.0.0", port: int = 8080):
        """Start gateway server"""
        try:
            await self.connect()
            
            app = self.create_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            
            logger.info(f"ARK Gateway listening on {host}:{port}")
            
            # Keep running
            await asyncio.Event().wait()
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.nc:
                await self.nc.close()


async def main():
    gateway = ARKGateway()
    await gateway.run()


if __name__ == "__main__":
    asyncio.run(main())
