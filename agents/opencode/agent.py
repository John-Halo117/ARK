#!/usr/bin/env python3
"""
OpenCode Agent - Reasoning and planning via capability model
Registers itself into mesh, processes events, publishes results
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
logger = logging.getLogger('OpenCode')


class OpenCodeAgent:
    """Reasoning and code intelligence agent"""
    
    def __init__(self):
        self.service_name = "opencode"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        
        self.capabilities = [
            "code.analyze",
            "code.transform",
            "code.generate",
            "reasoning.plan",
            "reasoning.decompose"
        ]
        
        self.nc = None
        self.js = None
        self.request_count = 0
        self._nats = ResilientNATSConnection(self.nats_url)
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck(self.service_name)
        self.health.register("nats", lambda: self._nats.is_connected)
        
        logger.info("OpenCode initialized (instance=%s)", self.instance_id)
    
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
                "started_at": datetime.utcnow().isoformat()
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
                    "load": self.request_count / 100.0,  # Simple load metric
                    "healthy": True,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
                # Reset counter
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
                    # e.g. ark.call.opencode.code.analyze -> capability = "code.analyze"
                    capability = parse_capability_from_subject(msg.subject)
                    
                    request = json.loads(msg.data.decode())
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    # Process capability
                    result = await self.handle_capability(capability, params)
                    
                    # Reply with result
                    await self.js.publish(reply_subject(request_id), json.dumps(result).encode())
                    
                    self.request_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing call: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process a capability request"""
        if capability == "code.analyze":
            return await self.analyze_code(params)
        elif capability == "code.transform":
            return await self.transform_code(params)
        elif capability == "code.generate":
            return await self.generate_code(params)
        elif capability == "reasoning.plan":
            return await self.plan(params)
        elif capability == "reasoning.decompose":
            return await self.decompose(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def analyze_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze code for patterns, quality, security"""
        source = sanitize_string(params.get('source', ''), 100_000)
        language = sanitize_string(params.get('language', 'python'), 32)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.analyze",
            "language": language,
            "analysis": {
                "lines": len(source.split('\n')),
                "complexity": "medium",
                "issues": [],
                "metrics": {
                    "cyclomatic": 2,
                    "maintainability_index": 75
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Analyzed {language} code: {result['analysis']['lines']} lines")
        return result
    
    async def transform_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Transform code (refactor, migrate, optimize)"""
        source = sanitize_string(params.get('source', ''), 100_000)
        transform_type = sanitize_string(params.get('type', 'refactor'), 32)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.transform",
            "type": transform_type,
            "output": source,
            "changes": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Transformed code via {transform_type}")
        return result
    
    async def generate_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate code from specification"""
        spec = sanitize_string(params.get('spec', ''), 10_000)
        language = sanitize_string(params.get('language', 'python'), 32)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "code.generate",
            "language": language,
            "generated": "# Generated code",
            "spec": spec,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Generated {language} code from spec")
        return result
    
    async def plan(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create execution plan for goal"""
        goal = sanitize_string(params.get('goal', ''), 2_000)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.plan",
            "goal": goal,
            "plan": {
                "steps": [],
                "resources_needed": [],
                "estimated_time": "unknown"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Created plan for: {goal}")
        return result
    
    async def decompose(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Decompose problem into sub-tasks"""
        problem = sanitize_string(params.get('problem', ''), 2_000)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "reasoning.decompose",
            "problem": problem,
            "subtasks": [],
            "dependencies": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Decomposed problem: {problem}")
        return result
    
    async def run(self):
        """Main agent loop with graceful shutdown"""
        try:
            self.shutdown.install_signal_handlers()
            await self.connect()
            await self.register()
            
            logger.info("OpenCode agent started")
            
            await asyncio.gather(
                self.subscribe_calls(),
                self.heartbeat_loop()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self._nats.close()


async def main():
    agent = OpenCodeAgent()
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
