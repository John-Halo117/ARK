#!/usr/bin/env python3
"""
UniFi Network Event Emitter - Monitors network devices and events
Emits network events into ARK for processing
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any, List

import aiohttp
from ark.config import load_unifi_config
from ark.emitter_contracts import (
    build_unifi_device_online_plan,
    build_unifi_device_status_change_plan,
    build_unifi_network_metric_plan,
)
from ark.event_schema import EventSource
from ark.gsb import GlobalStateBus, build_global_state_bus
from ark.reducers import KeyedItemsReducer, ReducerEngine
from ark.runtime_contracts import runtime_contract_registry
from ark.runtime_flow import DispatchDescriptor, DispatchRegistry, RuntimeAudit
try:
    import nats
    from nats.errors import Error as NATSError
except ImportError:  # pragma: no cover - local import/test environments
    nats = None
    NATSError = RuntimeError

from ark.subjects import (
    MESH_REGISTER, MESH_HEARTBEAT,
    EVENT_NETWORK_DEVICE, METRICS_NETWORK,
    call_subscribe_subject, reply_subject, parse_capability_from_subject,
)
from ark.time_utils import utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('UniFi-Emitter')


class UniFiEmitter:
    """Emits UniFi network events into ARK"""
    
    def __init__(self):
        config = load_unifi_config()
        self.service_name = "unifi"
        self.instance_id = config.runtime.instance_id
        self.nats_url = config.runtime.nats_url
        self.unifi_url = config.unifi_url
        self.unifi_username = config.unifi_username
        self.unifi_password = config.unifi_password
        self.unifi_site = config.unifi_site
        self.unifi_ca_bundle = config.unifi_ca_bundle
        
        self.capabilities = [
            "network.devices",
            "network.events",
            "network.stats",
            "device.status",
            "wireless.clients",
            "network.health"
        ]
        
        self.nc = None
        self.js = None
        self.session = None
        self.event_count = 0
        self.auth_cookie = None
        self.gsb: GlobalStateBus = build_global_state_bus()
        self.audit = RuntimeAudit(
            self.gsb,
            source=EventSource.EMITTER_UNIFI.value,
            surface="emitter",
            default_tags={"emitter": self.service_name},
        )
        self.contracts = runtime_contract_registry()
        self.reducer_engine = ReducerEngine(
            (
                KeyedItemsReducer(
                    name="emitter.unifi.devices",
                    key_field="device_id",
                    upsert_event="unifi.device_observed",
                ),
            )
        )
        self.tracked_devices: Dict[str, Any] = self.reducer_engine.view("emitter.unifi.devices")["items"]
        self.dispatch = DispatchRegistry(
            (
                DispatchDescriptor("network.devices", self.get_devices),
                DispatchDescriptor("network.events", self.get_events),
                DispatchDescriptor("network.stats", self.get_stats),
                DispatchDescriptor("device.status", self.get_device_status),
                DispatchDescriptor("wireless.clients", self.get_wireless_clients),
                DispatchDescriptor("network.health", self.get_network_health),
            ),
            contracts=self.contracts,
        )
        
        logger.info(f"UniFi Emitter initialized (instance={self.instance_id})")
    
    async def connect(self):
        """Connect to NATS and authenticate with UniFi"""
        if nats is None:
            raise RuntimeError("nats package is not installed")
        try:
            # UniFi controllers typically use self-signed certificates.
            # Set UNIFI_CA_BUNDLE to a CA cert path to enable verification.
            if self.unifi_ca_bundle:
                try:
                    import ssl as _ssl
                    ssl_ctx = _ssl.create_default_context(cafile=self.unifi_ca_bundle)
                    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                except (FileNotFoundError, OSError) as e:
                    logger.warning(
                        f"UNIFI_CA_BUNDLE path '{self.unifi_ca_bundle}' is invalid ({e}). "
                        "Falling back to SSL verification disabled."
                    )
                    connector = aiohttp.TCPConnector(ssl=False)
            else:
                logger.warning(
                    "SSL verification disabled for UniFi (self-signed cert). "
                    "Set UNIFI_CA_BUNDLE to a CA cert path to enable verification."
                )
                connector = aiohttp.TCPConnector(ssl=False)
            self.session = aiohttp.ClientSession(connector=connector)
            
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            
            # Authenticate with UniFi
            await self.authenticate_unifi()
            
            logger.info(f"Connected to NATS and UniFi at {self.unifi_url}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise
    
    async def authenticate_unifi(self):
        """Authenticate with UniFi controller"""
        if not self.unifi_username or not self.unifi_password:
            logger.warning("UniFi credentials not configured")
            return
        
        try:
            auth_data = {
                "username": self.unifi_username,
                "password": self.unifi_password,
                "remember": True
            }
            
            async with self.session.post(
                f"{self.unifi_url}/api/auth/login",
                json=auth_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status in (200, 201):
                    logger.info("Authenticated with UniFi")
                    # Session cookies are automatically stored
                else:
                    logger.warning(f"UniFi auth failed: {resp.status}")
        
        except Exception as e:
            logger.error(f"UniFi authentication error: {e}")
    
    async def register(self):
        """Register with ARK mesh"""
        event = {
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "metadata": {
                "version": "1.0.0",
                "unifi_url": self.unifi_url,
                "unifi_site": self.unifi_site,
                "started_at": utc_now_iso()
            },
            "ttl": 10
        }
        
        await self._publish_nats(self.nc, MESH_REGISTER, event, "emitter.register")
        logger.info(f"Registered with mesh: {self.capabilities}")
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats"""
        while True:
            await asyncio.sleep(5)
            
            try:
                await self._publish_nats(self.nc, MESH_HEARTBEAT, {
                    "service": self.service_name,
                    "instance_id": self.instance_id,
                    "load": self.event_count / 100.0,
                    "healthy": True,
                    "timestamp": utc_now_iso()
                }, "emitter.heartbeat")
                
                self.event_count = 0
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def monitor_devices(self):
        """Monitor network devices and emit events"""
        while True:
            try:
                devices = await self.fetch_devices()
                clients = await self.fetch_clients()
                
                for device in devices:
                    device_id = device.get('_id', '')
                    device_name = device.get('name', 'unknown')
                    status = device.get('state', 'unknown')
                    ip_address = device.get('ip', 'unknown')
                    
                    # Check if device is new or changed state
                    if device_id in self.tracked_devices:
                        prev = self.tracked_devices[device_id]
                        if prev.get('status') != status:
                            # Status changed
                            await self.emit_device_status_change(
                                device_id, device_name, ip_address, prev.get('status'), status
                            )
                    else:
                        # New device
                        await self.emit_device_online(device_id, device_name, ip_address)
                    
                    # Update tracked device
                    self.reducer_engine.apply(
                        "unifi.device_observed",
                        {
                            "device_id": device_id,
                            "value": {
                                "name": device_name,
                                "status": status,
                                "ip": ip_address,
                                "last_update": utc_now_iso(),
                            },
                        },
                    )
                
                # Emit client count metric
                if clients:
                    await self.emit_network_metric(
                        "wireless_clients",
                        len(clients),
                        "count"
                    )
                
                # Emit device count metric
                await self.emit_network_metric(
                    "network_devices",
                    len(devices),
                    "count"
                )
                
                await asyncio.sleep(30)  # Poll every 30 seconds
            
            except Exception as e:
                logger.error(f"Device monitor error: {e}")
                await asyncio.sleep(30)
    
    async def fetch_devices(self) -> List[Dict[str, Any]]:
        """Fetch all devices from UniFi"""
        if not self.session:
            return []
        
        try:
            async with self.session.get(
                f"{self.unifi_url}/api/s/{self.unifi_site}/stat/device",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', [])
                else:
                    logger.warning(f"UniFi device fetch returned {resp.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error fetching devices: {e}")
            return []
    
    async def fetch_clients(self) -> List[Dict[str, Any]]:
        """Fetch all wireless clients from UniFi"""
        if not self.session:
            return []
        
        try:
            async with self.session.get(
                f"{self.unifi_url}/api/s/{self.unifi_site}/stat/sta",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', [])
                else:
                    logger.warning(f"UniFi client fetch returned {resp.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []
    
    async def emit_device_online(self, device_id: str, device_name: str, ip: str):
        """Emit device online event"""
        try:
            plan = build_unifi_device_online_plan(
                device_id=device_id,
                device_name=device_name,
                ip_address=ip,
                timestamp=utc_now_iso(),
            )
            await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
            
            logger.info(f"Device online: {device_name} ({ip})")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting device online: {e}")
    
    async def emit_device_status_change(self, device_id: str, device_name: str, 
                                       ip: str, old_status: str, new_status: str):
        """Emit device status change event"""
        try:
            plan = build_unifi_device_status_change_plan(
                device_id=device_id,
                device_name=device_name,
                ip_address=ip,
                old_status=old_status,
                new_status=new_status,
                timestamp=utc_now_iso(),
            )
            await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
            
            logger.info(f"Device status changed: {device_name} {old_status} → {new_status}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting device status change: {e}")
    
    async def emit_network_metric(self, metric_name: str, value: float, unit: str):
        """Emit network metric"""
        try:
            plan = build_unifi_network_metric_plan(
                metric_name=metric_name,
                value=value,
                unit=unit,
                timestamp=utc_now_iso(),
            )
            await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
        
        except Exception as e:
            logger.error(f"Error emitting network metric: {e}")
    
    async def subscribe_capability_requests(self):
        """Subscribe to capability requests for UniFi operations"""
        try:
            sub = await self.nc.subscribe(call_subscribe_subject(self.service_name))
            logger.info("Subscribed to capability requests")
            
            async for msg in sub.messages:
                try:
                    capability = parse_capability_from_subject(msg.subject)
                    
                    request = self.contracts.materialize_payload(
                        "runtime.capability.call_message",
                        json.loads(msg.data.decode()),
                    )
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    result = await self.handle_capability(capability, params)
                    
                    await self._publish_nats(self.js, reply_subject(request_id), result, "emitter.reply")
                    
                    self.event_count += 1
                
                except Exception as e:
                    logger.error(f"Error processing capability: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle capability requests"""
        return await self.audit.execute(self.dispatch, capability, params)
    
    async def get_devices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get all network devices"""
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "network.devices",
            "devices": list(self.tracked_devices.values()),
            "total_devices": len(self.tracked_devices),
            "timestamp": utc_now_iso()
        }
    
    async def get_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get recent network events"""
        return {
            "agent": self.service_name,
            "capability": "network.events",
            "events": [],
            "timestamp": utc_now_iso()
        }
    
    async def get_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get network statistics"""
        devices = await self.fetch_devices()
        clients = await self.fetch_clients()
        
        return {
            "agent": self.service_name,
            "capability": "network.stats",
            "device_count": len(devices),
            "client_count": len(clients),
            "timestamp": utc_now_iso()
        }
    
    async def get_device_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get status of a specific device"""
        device_id = params.get('device_id', '')
        
        if device_id in self.tracked_devices:
            return {
                "agent": self.service_name,
                "capability": "device.status",
                "device_id": device_id,
                "info": self.tracked_devices[device_id],
                "timestamp": utc_now_iso()
            }
        
        return {
            "error": f"Device not found: {device_id}",
            "device_id": device_id
        }
    
    async def get_wireless_clients(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get wireless clients"""
        clients = await self.fetch_clients()
        
        return {
            "agent": self.service_name,
            "capability": "wireless.clients",
            "clients": clients,
            "total_clients": len(clients),
            "timestamp": utc_now_iso()
        }
    
    async def get_network_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get overall network health"""
        devices = await self.fetch_devices()
        clients = await self.fetch_clients()
        
        # Simple health calculation
        online_devices = sum(1 for d in devices if d.get('state') == 'connected')
        health_score = 100 if len(devices) == 0 else (online_devices / len(devices)) * 100
        
        return {
            "agent": self.service_name,
            "capability": "network.health",
            "health_score": health_score,
            "online_devices": online_devices,
            "total_devices": len(devices),
            "connected_clients": len(clients),
            "status": "healthy" if health_score >= 90 else "degraded" if health_score >= 70 else "critical",
            "timestamp": utc_now_iso()
        }

    async def _publish_nats(self, target: Any, subject: str, payload: Dict[str, Any], capability: str) -> None:
        await self.audit.publish_json(target, subject, payload, capability)
    
    async def run(self):
        """Main emitter loop"""
        try:
            await self.connect()
            await self.register()
            
            logger.info("UniFi emitter started")
            
            await asyncio.gather(
                self.monitor_devices(),
                self.heartbeat_loop(),
                self.subscribe_capability_requests()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.session:
                await self.session.close()
            if self.nc:
                await self.nc.close()


async def main():
    emitter = UniFiEmitter()
    await emitter.run()


if __name__ == "__main__":
    asyncio.run(main())
