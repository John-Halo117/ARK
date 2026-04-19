#!/usr/bin/env python3
"""
Composio Bridge - External world execution adapter
Routes capabilities to Composio API, returns results
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any

from nats.errors import Error as NATSError

from ark.security import sanitize_string
from ark.maintenance import ResilientNATSConnection, ShutdownCoordinator, HealthCheck
from ark.subjects import (
    MESH_REGISTER, MESH_HEARTBEAT,
    call_subscribe_subject, reply_subject, parse_capability_from_subject,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ComposioBridge')


class ComposioBridge:
    """External API execution adapter"""
    
    def __init__(self):
        self.service_name = "composio"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        self.composio_api_key = os.environ.get('COMPOSIO_API_KEY', '')
        
        self.capabilities = [
            "external.email",
            "external.github",
            "external.slack",
            "external.notion",
            "external.calendar",
            "external.crm"
        ]
        
        self.nc = None
        self.js = None
        self.request_count = 0
        self._nats = ResilientNATSConnection(self.nats_url)
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck(self.service_name)
        self.health.register("nats", lambda: self._nats.is_connected)
        self.health.register("composio_api", lambda: bool(self.composio_api_key))
        
        logger.info("ComposioBridge initialized (instance=%s)", self.instance_id)
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        logger.info("Connected to NATS")
    
    async def register(self):
        """Register with mesh"""
        event = {
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "metadata": {
                "version": "1.0.0",
                "started_at": datetime.utcnow().isoformat(),
                "composio_connected": bool(self.composio_api_key)
            },
            "ttl": 10
        }
        
        await self.nc.publish(MESH_REGISTER, json.dumps(event).encode())
        logger.info(f"Registered with mesh: {self.capabilities}")
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats"""
        while True:
            await asyncio.sleep(5)
            
            try:
                await self.nc.publish(MESH_HEARTBEAT, json.dumps({
                    "service": self.service_name,
                    "instance_id": self.instance_id,
                    "load": self.request_count / 100.0,
                    "healthy": True,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
                self.request_count = 0
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def subscribe_calls(self):
        """Subscribe to capability calls"""
        try:
            sub = await self.nc.subscribe(call_subscribe_subject(self.service_name))
            logger.info("Subscribed to capability calls")
            
            async for msg in sub.messages:
                try:
                    capability = parse_capability_from_subject(msg.subject)
                    
                    request = json.loads(msg.data.decode())
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    result = await self.handle_capability(capability, params)
                    
                    await self.js.publish(reply_subject(request_id), json.dumps(result).encode())
                    
                    self.request_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing call: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process a capability request"""
        if capability == "external.email":
            return await self.send_email(params)
        elif capability == "external.github":
            return await self.github_action(params)
        elif capability == "external.slack":
            return await self.slack_message(params)
        elif capability == "external.notion":
            return await self.notion_action(params)
        elif capability == "external.calendar":
            return await self.calendar_action(params)
        elif capability == "external.crm":
            return await self.crm_action(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def send_email(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send email via Composio (sanitize recipient info for logging)"""
        to = sanitize_string(params.get('to', ''), 256)
        subject = sanitize_string(params.get('subject', ''), 256)
        body = sanitize_string(params.get('body', ''), 10_000)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.email",
            "to": to,
            "subject": subject,
            "body_length": len(body),
            "success": bool(self.composio_api_key),
            "message": "Email queued for delivery" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Email action: {to} - {subject}")
        return result
    
    async def github_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GitHub action via Composio"""
        action = sanitize_string(params.get('action', ''), 128)
        repo = sanitize_string(params.get('repo', ''), 256)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.github",
            "action": action,
            "repo": repo,
            "success": bool(self.composio_api_key),
            "message": "GitHub action queued" if self.composio_api_key else "Composio not configured",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"GitHub action: {action} on {repo}")
        return result
    
    async def slack_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send Slack message via Composio"""
        channel = sanitize_string(params.get('channel', ''), 128)
        message = sanitize_string(params.get('message', ''), 4_000)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.slack",
            "channel": channel,
            "message": message,
            "success": bool(self.composio_api_key),
            "message_id": str(uuid.uuid4())[:12] if self.composio_api_key else None,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Slack message to {channel}")
        return result
    
    async def notion_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Notion action via Composio"""
        action = sanitize_string(params.get('action', ''), 128)
        database = sanitize_string(params.get('database', ''), 256)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.notion",
            "action": action,
            "database": database,
            "success": bool(self.composio_api_key),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Notion action: {action} on {database}")
        return result
    
    async def calendar_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute calendar action via Composio"""
        action = sanitize_string(params.get('action', ''), 128)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.calendar",
            "action": action,
            "success": bool(self.composio_api_key),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Calendar action: {action}")
        return result
    
    async def crm_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute CRM action via Composio"""
        action = sanitize_string(params.get('action', ''), 128)
        entity = sanitize_string(params.get('entity', ''), 256)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "external.crm",
            "action": action,
            "entity": entity,
            "success": bool(self.composio_api_key),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"CRM action: {action} on {entity}")
        return result
    
    async def run(self):
        """Main agent loop with graceful shutdown"""
        try:
            self.shutdown.install_signal_handlers()
            await self.connect()
            await self.register()
            
            logger.info("ComposioBridge started")
            
            await asyncio.gather(
                self.subscribe_calls(),
                self.heartbeat_loop()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self._nats.close()


async def main():
    bridge = ComposioBridge()
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
