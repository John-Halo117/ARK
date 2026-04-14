#!/usr/bin/env python3
"""
UniFi Network Event Emitter - Monitors network devices and events
Emits network events into ARK for processing
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List

import aiohttp
import nats
from nats.errors import Error as NATSError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('UniFi-Emitter')


class UniFiEmitter:
    """Emits UniFi network events into ARK"""
    
    def __init__(self):
        self.service_name = "unifi"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        self.unifi_url = os.environ.get('UNIFI_URL', 'https://unifi:8443')
        self.unifi_username = os.environ.get('UNIFI_USERNAME', '')
        self.unifi_password = os.environ.get('UNIFI_PASSWORD', '')
        self.unifi_site = os.environ.get('UNIFI_SITE', 'default')
        
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
        self.tracked_devices: Dict[str, Any] = {}
        self.auth_cookie = None
        
        logger.info(f"UniFi Emitter initialized (instance={self.instance_id})")
    
    async def connect(self):
        """Connect to NATS and authenticate with UniFi"""
        try:
            # UniFi controllers typically use self-signed certificates.
            # Set UNIFI_CA_BUNDLE to a CA cert path to enable verification.
            ca_bundle = os.environ.get('UNIFI_CA_BUNDLE', '')
            if ca_bundle:
                try:
                    import ssl as _ssl
                    ssl_ctx = _ssl.create_default_context(cafile=ca_bundle)
                    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                except (FileNotFoundError, OSError) as e:
                    logger.warning(
                        f"Failed to load CA bundle '{ca_bundle}': {e}. "
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
                "started_at": datetime.utcnow().isoformat()
            },
            "ttl": 10
        }
        
        await self.nc.publish("ark.mesh.register", json.dumps(event).encode())
        logger.info(f"Registered with mesh: {self.capabilities}")
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats"""
        while True:
            await asyncio.sleep(5)
            
            try:
                await self.nc.publish("ark.mesh.heartbeat", json.dumps({
                    "service": self.service_name,
                    "instance_id": self.instance_id,
                    "load": self.event_count / 100.0,
                    "healthy": True,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
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
                    self.tracked_devices[device_id] = {
                        "name": device_name,
                        "status": status,
                        "ip": ip_address,
                        "last_update": datetime.utcnow().isoformat()
                    }
                
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
            event = {
                "event": "device_online",
                "device_id": device_id,
                "device_name": device_name,
                "ip_address": ip,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "unifi"
            }
            
            await self.js.publish("ark.event.network.device", json.dumps(event).encode())
            
            logger.info(f"Device online: {device_name} ({ip})")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting device online: {e}")
    
    async def emit_device_status_change(self, device_id: str, device_name: str, 
                                       ip: str, old_status: str, new_status: str):
        """Emit device status change event"""
        try:
            event = {
                "event": "device_status_changed",
                "device_id": device_id,
                "device_name": device_name,
                "ip_address": ip,
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "unifi"
            }
            
            await self.js.publish("ark.event.network.device", json.dumps(event).encode())
            
            logger.info(f"Device status changed: {device_name} {old_status} → {new_status}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting device status change: {e}")
    
    async def emit_network_metric(self, metric_name: str, value: float, unit: str):
        """Emit network metric"""
        try:
            await self.js.publish("ark.metrics.network", json.dumps({
                "name": f"network.{metric_name}",
                "value": value,
                "unit": unit,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "unifi"
            }).encode())
        
        except Exception as e:
            logger.error(f"Error emitting network metric: {e}")
    
    async def subscribe_capability_requests(self):
        """Subscribe to capability requests for UniFi operations"""
        try:
            sub = await self.nc.subscribe(f"ark.call.{self.service_name}.*")
            logger.info("Subscribed to capability requests")
            
            async for msg in sub.messages:
                try:
                    subject_parts = msg.subject.split('.')
                    capability = subject_parts[-1] if len(subject_parts) >= 4 else "unknown"
                    
                    request = json.loads(msg.data.decode())
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    result = await self.handle_capability(capability, params)
                    
                    reply_topic = f"ark.reply.{request_id}"
                    await self.js.publish(reply_topic, json.dumps(result).encode())
                    
                    self.event_count += 1
                
                except Exception as e:
                    logger.error(f"Error processing capability: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle capability requests"""
        if capability == "network.devices":
            return await self.get_devices(params)
        elif capability == "network.events":
            return await self.get_events(params)
        elif capability == "network.stats":
            return await self.get_stats(params)
        elif capability == "device.status":
            return await self.get_device_status(params)
        elif capability == "wireless.clients":
            return await self.get_wireless_clients(params)
        elif capability == "network.health":
            return await self.get_network_health(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def get_devices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get all network devices"""
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "network.devices",
            "devices": list(self.tracked_devices.values()),
            "total_devices": len(self.tracked_devices),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def get_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get recent network events"""
        return {
            "agent": self.service_name,
            "capability": "network.events",
            "events": [],
            "timestamp": datetime.utcnow().isoformat()
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
            "timestamp": datetime.utcnow().isoformat()
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
                "timestamp": datetime.utcnow().isoformat()
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
            "timestamp": datetime.utcnow().isoformat()
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
            "timestamp": datetime.utcnow().isoformat()
        }
    
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
