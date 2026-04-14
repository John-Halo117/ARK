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
from ark.security import (
    auth_middleware,
    clamp_limit,
    error_shield_middleware,
    rate_limit_middleware,
    request_id_middleware,
    sanitize_string,
    secure_headers_middleware,
    validate_capability,
    validate_payload,
    validate_service_name,
)
from ark.maintenance import (
    HealthCheck,
    ResilientNATSConnection,
    ShutdownCoordinator,
)

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
        self._nats = ResilientNATSConnection(self.nats_url)
        self.nc = None
        self.js = None
        self.db = DuckClient()
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck("ark-gateway")
        self.health.register("nats", lambda: self._nats.is_connected)
        self.health.register("db", lambda: self.db.conn is not None)
        
        logger.info("ARK Gateway initialized")
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        logger.info("Connected to NATS")
    
    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health - Liveness / readiness probe"""
        status = self.health.check()
        code = 200 if status["healthy"] else 503
        return web.json_response(status, status=code)

    async def handle_mesh_status(self, request: web.Request) -> web.Response:
        """GET /api/mesh - Get mesh registry status"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.mesh_url}/api/mesh",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception:
            logger.exception("Mesh query error")
            return web.json_response({"error": "mesh unavailable"}, status=502)
    
    async def handle_service_info(self, request: web.Request) -> web.Response:
        """GET /api/service/{name} - Get service info"""
        service = request.match_info.get('name', '')
        try:
            validate_service_name(service)
        except ValueError:
            return web.json_response({"error": "invalid service name"}, status=400)
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.mesh_url}/api/service/{service}",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception:
            logger.exception("Service info error for %s", service)
            return web.json_response({"error": "service query failed"}, status=502)
    
    async def handle_route_capability(self, request: web.Request) -> web.Response:
        """GET /api/route/{capability} - Get best instance for capability"""
        capability = request.match_info.get('capability', '')
        try:
            validate_capability(capability)
        except ValueError:
            return web.json_response({"error": "invalid capability"}, status=400)
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.mesh_url}/api/route/{capability}",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                    return web.json_response(data)
        except Exception:
            logger.exception("Route capability error for %s", capability)
            return web.json_response({"error": "routing failed"}, status=502)
    
    async def handle_call_capability(self, request: web.Request) -> web.Response:
        """POST /api/call/{capability} - Call a capability"""
        capability = request.match_info.get('capability', '')
        try:
            validate_capability(capability)
        except ValueError:
            return web.json_response({"error": "invalid capability"}, status=400)
        
        try:
            body = await request.json()
            request_id = sanitize_string(body.get('request_id', '').strip(), 128) or None
            params = validate_payload(body.get('params', {}))
            
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
            logger.exception("Capability call error")
            return web.json_response({"error": "capability call failed"}, status=500)
    
    async def handle_query_events(self, request: web.Request) -> web.Response:
        """GET /api/events?source=X&type=Y&limit=Z - Query events"""
        try:
            source = request.rel_url.query.get('source')
            event_type = request.rel_url.query.get('type')
            if source:
                source = sanitize_string(source, 128)
            if event_type:
                event_type = sanitize_string(event_type, 64)
            limit = clamp_limit(request.rel_url.query.get('limit', 100))
            
            events = self.db.query_events(source, event_type, limit)
            
            return web.json_response({
                "count": len(events),
                "events": events
            })
        except Exception:
            logger.exception("Event query error")
            return web.json_response({"error": "event query failed"}, status=500)
    
    async def handle_query_metrics(self, request: web.Request) -> web.Response:
        """GET /api/metrics/{source} - Get latest LKS metrics"""
        source = sanitize_string(request.match_info.get('source', ''), 128)
        limit = clamp_limit(request.rel_url.query.get('limit', 10), default=10, ceiling=1000)
        
        try:
            metrics = self.db.get_latest_lks(source, limit)
            return web.json_response({
                "source": source,
                "count": len(metrics),
                "metrics": metrics
            })
        except Exception:
            logger.exception("Metrics query error for %s", source)
            return web.json_response({"error": "metrics query failed"}, status=500)
    
    async def handle_system_status(self, request: web.Request) -> web.Response:
        """GET /api/status - Overall system status"""
        try:
            # Mesh status
            import aiohttp
            mesh_data = None
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.mesh_url}/api/mesh",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        mesh_data = await resp.json()
            except Exception:
                logger.debug("Mesh status unavailable")
            
            # DB status
            db_data = self.db.get_mesh_status()
            
            return web.json_response({
                "timestamp": datetime.utcnow().isoformat(),
                "mesh": mesh_data or {"error": "unavailable"},
                "database": db_data,
                "gateway": "healthy"
            })
        except Exception:
            logger.exception("System status error")
            return web.json_response({"error": "status unavailable"}, status=500)
    
    def create_app(self) -> web.Application:
        """Create aiohttp application with security middleware"""
        app = web.Application(
            middlewares=[
                request_id_middleware,
                error_shield_middleware,
                secure_headers_middleware,
                rate_limit_middleware,
                auth_middleware,
            ],
            client_max_size=2 * 1024 * 1024,  # 2 MiB body limit
        )
        
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
        app.router.add_get('/api/health', self.handle_health)
        
        return app
    
    async def run(self, host: str = "0.0.0.0", port: int = 8080):
        """Start gateway server with graceful shutdown"""
        runner = None
        try:
            self.shutdown.install_signal_handlers()
            await self.connect()
            
            app = self.create_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            
            logger.info("ARK Gateway listening on %s:%d", host, port)
            
            # Keep running until shutdown
            await self.shutdown.wait_for_shutdown()
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if runner:
                await runner.cleanup()
            await self._nats.close()
            logger.info("Gateway shutdown complete")


async def main():
    gateway = ARKGateway()
    await gateway.run()


if __name__ == "__main__":
    asyncio.run(main())
