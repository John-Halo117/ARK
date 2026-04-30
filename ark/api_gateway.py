#!/usr/bin/env python3
"""
ARK API Gateway - Unified entry point for system queries and operations
Routes to: Mesh, DuckDB, agents, storage
"""

import asyncio
import json
import logging
from typing import Optional

import aiohttp
from aiohttp import web
from ark.config import load_gateway_config
from ark.duck_client import DuckClient
from ark.event_schema import EventSource
from ark.gsb import DuckGSBSink, GlobalStateBus, build_global_state_bus
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
from ark.runtime_contracts import runtime_contract_registry
from ark.runtime_flow import RuntimeAudit
from ark.subjects import call_subject
from ark.time_utils import utc_now_iso, utc_timestamp
from ark.web_console import (
    CONSOLE_STATIC_DIR,
    ConsoleFailure,
    WebConsoleService,
    failure,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ARK-Gateway')


class ARKGateway:
    """API Gateway for ARK system"""
    
    def __init__(self):
        config = load_gateway_config()
        self.nats_url = config.nats_url
        self.mesh_url = config.mesh_url
        self._nats = ResilientNATSConnection(self.nats_url)
        self.nc = None
        self.js = None
        self.db = DuckClient()
        self.gsb: GlobalStateBus = build_global_state_bus(DuckGSBSink(self.db))
        self.audit = RuntimeAudit(
            self.gsb,
            source=EventSource.ARK_CORE.value,
            surface="gateway",
            default_tags={"surface": "gateway"},
        )
        self.contracts = runtime_contract_registry()
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck("ark-gateway")
        self.health.register("nats", lambda: self._nats.is_connected)
        self.health.register("db", lambda: self.db.conn is not None)
        self.health.register("gsb", lambda: self.gsb.health()["enabled"])
        self.console = WebConsoleService(self.db, self.mesh_url)
        self._http_session: Optional[aiohttp.ClientSession] = None
        
        logger.info("ARK Gateway initialized")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a reusable HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )
        return self._http_session
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        self._http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        )
        logger.info("Connected to NATS")
    
    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health - Liveness / readiness probe"""
        blocked = self._record_gsb(request, "gateway.health", "gateway.health.query", {})
        if blocked:
            return blocked
        status = self.health.check()
        code = 200 if status["healthy"] else 503
        return web.json_response(status, status=code)

    async def handle_mesh_status(self, request: web.Request) -> web.Response:
        """GET /api/mesh - Get mesh registry status"""
        blocked = self._record_gsb(request, "gateway.mesh", "gateway.mesh.status", {})
        if blocked:
            return blocked
        try:
            session = await self._get_session()
            async with session.get(f"{self.mesh_url}/api/mesh") as resp:
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
        blocked = self._record_gsb(request, "gateway.service", "gateway.service.info", {"service": service})
        if blocked:
            return blocked
        try:
            session = await self._get_session()
            async with session.get(f"{self.mesh_url}/api/service/{service}") as resp:
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
        blocked = self._record_gsb(request, "gateway.route", capability, {})
        if blocked:
            return blocked
        try:
            session = await self._get_session()
            async with session.get(f"{self.mesh_url}/api/route/{capability}") as resp:
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
            request_id, params = await self._parse_call_body(request)
            blocked = self._record_gsb(request, "gateway.call", capability, {"params": params})
            if blocked:
                return blocked
            route = await self._fetch_route(capability)
            if route is None:
                return web.json_response({"error": "No service available"}, status=404)
            service, instance_id = route.get('service'), route.get('instance_id')
            if not service or not instance_id:
                return web.json_response({"error": "No route available"}, status=404)
            call_msg = self._build_call_msg(request_id, service, instance_id, capability, params)
            await self._publish_call(call_msg)
            logger.info(f"Routed capability {capability} to {service}/{instance_id}")
            return web.json_response(self._queued_response(call_msg))
        
        except Exception:
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
            blocked = self._record_gsb(
                request,
                "gateway.events",
                "gateway.events.query",
                {"source": source or "", "event_type": event_type or "", "limit": limit},
            )
            if blocked:
                return blocked
            
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
        blocked = self._record_gsb(
            request,
            "gateway.metrics",
            "gateway.metrics.query",
            {"source": source, "limit": limit},
        )
        if blocked:
            return blocked
        
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
        blocked = self._record_gsb(request, "gateway.status", "gateway.status.query", {})
        if blocked:
            return blocked
        try:
            # Mesh status
            mesh_data = None
            try:
                session = await self._get_session()
                async with session.get(f"{self.mesh_url}/api/mesh") as resp:
                    mesh_data = await resp.json()
            except Exception:
                logger.debug("Mesh status unavailable")
            
            # DB status
            db_data = self.db.get_mesh_status()
            
            return web.json_response({
                "timestamp": utc_now_iso(),
                "mesh": mesh_data or {"error": "unavailable"},
                "database": db_data,
                "gateway": "healthy"
            })
        except Exception:
            logger.exception("System status error")
            return web.json_response({"error": "status unavailable"}, status=500)

    async def handle_console_index(self, request: web.Request) -> web.Response:
        """GET /console - Local web console shell."""
        index_path = CONSOLE_STATIC_DIR / "index.html"
        if not index_path.is_file():
            return web.json_response(
                failure("CONSOLE_STATIC_MISSING", "console index is not available", {"path": str(index_path)}, True),
                status=503,
            )
        return web.FileResponse(index_path)

    async def handle_console_status(self, request: web.Request) -> web.Response:
        """GET /api/console/status - Bounded health overview."""
        blocked = self._record_gsb(request, "console.status", "console.status.query", {})
        if blocked:
            return blocked
        try:
            session = await self._get_session()
            return web.json_response(await self.console.health_snapshot(session))
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console status error")
            return web.json_response(
                failure("CONSOLE_STATUS_FAILED", "console status query failed", {}, True),
                status=500,
            )

    async def handle_console_events(self, request: web.Request) -> web.Response:
        """GET /api/console/events - Bounded cursor event page."""
        try:
            source = request.rel_url.query.get("source")
            event_type = request.rel_url.query.get("type")
            limit = int(request.rel_url.query.get("limit", "50"))
            cursor_raw = request.rel_url.query.get("cursor")
            cursor = int(cursor_raw) if cursor_raw else None
            blocked = self._record_gsb(
                request,
                "console.events",
                "console.events.query",
                {"source": source or "", "event_type": event_type or "", "limit": limit, "cursor": cursor or 0},
            )
            if blocked:
                return blocked
            return web.json_response(
                self.console.event_page(source=source, event_type=event_type, limit=limit, cursor=cursor)
            )
        except (TypeError, ValueError):
            return web.json_response(
                failure("CONSOLE_EVENT_QUERY_INVALID", "limit and cursor must be integers", {}, False),
                status=400,
            )
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console event query error")
            return web.json_response(
                failure("CONSOLE_EVENTS_FAILED", "console event query failed", {}, True),
                status=500,
            )

    async def handle_console_agents(self, request: web.Request) -> web.Response:
        """GET /api/console/agents - Capability registry snapshot."""
        blocked = self._record_gsb(request, "console.agents", "console.agents.query", {})
        if blocked:
            return blocked
        try:
            session = await self._get_session()
            return web.json_response(await self.console.agent_registry(session))
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console agent registry error")
            return web.json_response(
                failure("CONSOLE_AGENTS_FAILED", "console agent registry query failed", {}, True),
                status=500,
            )

    async def handle_console_trace(self, request: web.Request) -> web.Response:
        """POST /api/console/trace - Deterministic decision trace preview."""
        try:
            body = await request.json()
            blocked = self._record_gsb(request, "console.trace", "console.trace.preview", {})
            if blocked:
                return blocked
            return web.json_response(self.console.decision_trace(body))
        except json.JSONDecodeError:
            return web.json_response(
                failure("CONSOLE_JSON_INVALID", "request body must be valid json", {}, False),
                status=400,
            )
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console trace error")
            return web.json_response(
                failure("CONSOLE_TRACE_FAILED", "console decision trace failed", {}, True),
                status=500,
            )

    async def handle_console_state(self, request: web.Request) -> web.Response:
        """GET /state - Read-only S projection."""
        blocked = self._record_gsb(request, "console.state", "console.state.read", {})
        if blocked:
            return blocked
        try:
            return web.json_response(self.console.state_snapshot())
        except Exception:
            logger.exception("Console state read error")
            return web.json_response(
                failure("CONSOLE_STATE_FAILED", "console state read failed", {}, True),
                status=500,
            )

    async def handle_console_action(self, request: web.Request) -> web.Response:
        """POST /action - Gate every action before queueing execution."""
        try:
            body = await request.json()
            gated = self.console.action_gate(body, simulation=False)
            blocked = self._record_gsb(
                request,
                "console.action",
                str(gated["intent"]["action"]),
                {"status": gated["status"], "event_hash": gated["event"]["hash"]},
            )
            if blocked:
                return blocked
            if gated["status"] == "BLOCKED":
                return web.json_response(gated, status=403)
            route = await self._fetch_route(str(gated["intent"]["action"]))
            if route is None:
                gated["status"] = "BLOCKED"
                gated["decision"] = {
                    **gated["decision"],
                    "status": "BLOCKED",
                    "decision": "block",
                    "reasons": [*gated["decision"]["reasons"], "route_unavailable"],
                    "executed": False,
                }
                gated["result"]["status"] = "BLOCKED"
                gated["result"]["output"]["blocked"] = True
                return web.json_response(gated, status=404)
            service, instance_id = route.get("service"), route.get("instance_id")
            if not service or not instance_id:
                gated["status"] = "BLOCKED"
                gated["decision"] = {
                    **gated["decision"],
                    "status": "BLOCKED",
                    "decision": "block",
                    "reasons": [*gated["decision"]["reasons"], "route_invalid"],
                    "executed": False,
                }
                gated["result"]["status"] = "BLOCKED"
                gated["result"]["output"]["blocked"] = True
                return web.json_response(gated, status=404)
            call_msg = self._build_call_msg(
                None,
                str(service),
                str(instance_id),
                str(gated["intent"]["action"]),
                {"event": gated["event"], "proof": gated["proof"], "params": gated["intent"]["params"]},
            )
            await self._publish_call(call_msg)
            gated["status"] = "QUEUED"
            gated["decision"] = {**gated["decision"], "executed": True, "queued": True}
            gated["result"]["status"] = "QUEUED"
            gated["result"]["output"] = {**gated["result"]["output"], "executed": True, "queued": True, "request_id": call_msg["request_id"]}
            return web.json_response(gated)
        except json.JSONDecodeError:
            return web.json_response(
                failure("CONSOLE_JSON_INVALID", "request body must be valid json", {}, False),
                status=400,
            )
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console action error")
            return web.json_response(
                failure("CONSOLE_ACTION_FAILED", "console action failed", {}, True),
                status=500,
            )

    async def handle_console_config_index(self, request: web.Request) -> web.Response:
        """GET /api/console/config - Read-only config index."""
        blocked = self._record_gsb(request, "console.config", "console.config.index", {})
        if blocked:
            return blocked
        return web.json_response(self.console.config_index())

    async def handle_console_config_file(self, request: web.Request) -> web.Response:
        """GET /api/console/config/file?path=... - Read-only config content."""
        blocked = self._record_gsb(request, "console.config_file", "console.config.read", {})
        if blocked:
            return blocked
        try:
            return web.json_response(self.console.config_file(request.rel_url.query.get("path", "")))
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console config read error")
            return web.json_response(
                failure("CONSOLE_CONFIG_FAILED", "console config read failed", {}, True),
                status=500,
            )

    async def handle_console_test_ingest(self, request: web.Request) -> web.Response:
        """POST /api/console/test-ingest - Safe bounded console test event."""
        try:
            body = await request.json()
            blocked = self._record_gsb(request, "console.test_ingest", "console.test_ingest", {})
            if blocked:
                return blocked
            return web.json_response(self.console.safe_test_ingest(body))
        except json.JSONDecodeError:
            return web.json_response(
                failure("CONSOLE_JSON_INVALID", "request body must be valid json", {}, False),
                status=400,
            )
        except ConsoleFailure as exc:
            return web.json_response(exc.as_dict(), status=400)
        except Exception:
            logger.exception("Console test ingest error")
            return web.json_response(
                failure("CONSOLE_TEST_INGEST_FAILED", "console test ingest failed", {}, True),
                status=500,
            )
    
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

        # Local web console
        app.router.add_get('/', self.handle_console_index)
        app.router.add_get('/console', self.handle_console_index)
        app.router.add_get('/api/console/status', self.handle_console_status)
        app.router.add_get('/api/console/events', self.handle_console_events)
        app.router.add_get('/api/console/agents', self.handle_console_agents)
        app.router.add_post('/api/console/trace', self.handle_console_trace)
        app.router.add_get('/api/console/state', self.handle_console_state)
        app.router.add_get('/api/console/config', self.handle_console_config_index)
        app.router.add_get('/api/console/config/file', self.handle_console_config_file)
        app.router.add_post('/api/console/test-ingest', self.handle_console_test_ingest)
        app.router.add_get('/state', self.handle_console_state)
        app.router.add_post('/action', self.handle_console_action)
        if CONSOLE_STATIC_DIR.is_dir():
            app.router.add_static('/console/assets', CONSOLE_STATIC_DIR, show_index=False)
        
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
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
            await self._nats.close()
            logger.info("Gateway shutdown complete")

    def _record_gsb(
        self,
        request: web.Request,
        action: str,
        capability: str,
        payload: dict[str, object],
    ) -> web.Response | None:
        error = self.audit.record(
            action,
            capability,
            {**self._request_payload(request), **payload},
        )
        if error is None:
            return None
        return web.json_response(error, status=500)

    def _request_payload(self, request: web.Request) -> dict[str, object]:
        return {
            "method": request.method,
            "path": request.path,
            "request_id": sanitize_string(str(request.get("request_id", "")), 128),
        }

    async def _parse_call_body(self, request: web.Request) -> tuple[str | None, dict[str, object]]:
        body = self.contracts.materialize_payload("runtime.gateway.call_body", await request.json())
        request_id = sanitize_string(str(body.get('request_id', '')).strip(), 128) or None
        return request_id, validate_payload(body.get('params', {}))

    async def _fetch_route(self, capability: str) -> dict[str, object] | None:
        session = await self._get_session()
        async with session.get(f"{self.mesh_url}/api/route/{capability}") as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    def _build_call_msg(
        self,
        request_id: str | None,
        service: str,
        instance_id: str,
        capability: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        return self.contracts.materialize_payload(
            "runtime.capability.call_message",
            {
            "request_id": request_id or f"req-{instance_id}-{utc_timestamp()}",
            "service": service,
            "instance_id": instance_id,
            "capability": capability,
            "params": params,
            },
        )

    async def _publish_call(self, call_msg: dict[str, object]) -> None:
        await self._publish_nats(
            self.nc,
            call_subject(str(call_msg["service"]), str(call_msg["capability"])),
            call_msg,
            str(call_msg["capability"]),
        )

    async def _publish_nats(
        self,
        target: object,
        subject: str,
        payload: dict[str, object],
        capability: str,
    ) -> None:
        error = await self.audit.publish_json(target, subject, payload, capability)
        if error:
            raise RuntimeError(error["reason"])

    def _queued_response(self, call_msg: dict[str, object]) -> dict[str, object]:
        return {
            "request_id": call_msg["request_id"],
            "service": call_msg["service"],
            "instance_id": call_msg["instance_id"],
            "capability": call_msg["capability"],
            "status": "queued",
        }


async def main():
    gateway = ARKGateway()
    await gateway.run()


if __name__ == "__main__":
    asyncio.run(main())
