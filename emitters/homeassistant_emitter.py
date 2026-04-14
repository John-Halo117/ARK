#!/usr/bin/env python3
"""
Home Assistant Event Emitter - Monitors state changes and publishes events to ARK
Bridges Home Assistant events into NATS for processing by agents
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List

import aiohttp
from ark.security import validate_entity_id
import nats
from nats.errors import Error as NATSError

from ark.subjects import (
    MESH_REGISTER, MESH_HEARTBEAT, METRICS_TEMPERATURE,
    EVENT_STATE_CHANGE, EVENT_CLIMATE_TEMPERATURE, EVENT_LIGHT_TOGGLE,
    EVENT_SENSOR_READING,
    call_subscribe_subject, reply_subject, parse_capability_from_subject,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('HA-Emitter')


class HomeAssistantEmitter:
    """Emits Home Assistant state changes and events into ARK"""
    
    def __init__(self):
        self.service_name = "homeassistant"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        self.ha_url = os.environ.get('HA_URL', 'http://homeassistant:8123')
        self.ha_token = os.environ.get('HA_TOKEN', '')
        
        self.capabilities = [
            "event.home_assistant",
            "state.device_update",
            "automation.trigger",
            "climate.temperature",
            "light.toggle",
            "sensor.reading"
        ]
        
        self.nc = None
        self.js = None
        self.session = None
        self.event_count = 0
        self.tracked_entities: Dict[str, Any] = {}
        
        logger.info(f"HA Emitter initialized (instance={self.instance_id})")
    
    async def connect(self):
        """Connect to NATS and create HTTP session"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            self.session = aiohttp.ClientSession()
            logger.info(f"Connected to NATS and HA at {self.ha_url}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise
    
    async def register(self):
        """Register with ARK mesh"""
        event = {
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "metadata": {
                "version": "1.0.0",
                "ha_url": self.ha_url,
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
                    "load": self.event_count / 100.0,
                    "healthy": True,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
                self.event_count = 0
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def fetch_states(self) -> List[Dict[str, Any]]:
        """Fetch all entity states from Home Assistant"""
        if not self.session or not self.ha_token:
            logger.warning("HA session or token not configured")
            return []
        
        try:
            headers = {
                "Authorization": f"Bearer {self.ha_token}",
                "Content-Type": "application/json"
            }
            
            async with self.session.get(
                f"{self.ha_url}/api/states",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    states = await resp.json()
                    logger.info(f"Fetched {len(states)} entity states")
                    return states
                else:
                    logger.warning(f"HA API returned {resp.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error fetching states: {e}")
            return []
    
    async def poll_states(self):
        """Poll Home Assistant states periodically and detect changes"""
        previous_states = {}
        
        while True:
            try:
                states = await self.fetch_states()
                
                for state in states:
                    entity_id = state.get('entity_id', '')
                    current = state.get('state', '')
                    attributes = state.get('attributes', {})
                    
                    # Check if state changed
                    if entity_id in previous_states:
                        prev_state = previous_states[entity_id].get('state', '')
                        if prev_state != current:
                            # State changed
                            await self.emit_state_change(
                                entity_id, prev_state, current, attributes
                            )
                    
                    # Store current state
                    previous_states[entity_id] = state
                    self.tracked_entities[entity_id] = {
                        "state": current,
                        "attributes": attributes,
                        "last_change": datetime.utcnow().isoformat()
                    }
                
                await asyncio.sleep(5)  # Poll every 5 seconds
            
            except Exception as e:
                logger.error(f"State poll error: {e}")
                await asyncio.sleep(5)
    
    async def emit_state_change(self, entity_id: str, old_state: str, 
                                new_state: str, attributes: Dict[str, Any]):
        """Emit state change event to ARK"""
        try:
            # Determine event type by entity prefix
            entity_type = entity_id.split('.')[0]
            
            if entity_type == 'climate':
                topic = EVENT_CLIMATE_TEMPERATURE
                value = attributes.get('current_temperature', 0)
            elif entity_type == 'light':
                topic = EVENT_LIGHT_TOGGLE
                value = new_state
            elif entity_type == 'sensor':
                topic = EVENT_SENSOR_READING
                value = new_state
            else:
                topic = EVENT_STATE_CHANGE
                value = new_state
            
            event = {
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
                "attributes": attributes,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "homeassistant"
            }
            
            # Publish state change
            await self.js.publish(topic, json.dumps(event).encode())
            
            # Also emit to general event topic for agents to process,
            # but only if the typed topic differs (avoids duplicate publish
            # for generic entities whose topic is already EVENT_STATE_CHANGE).
            if topic != EVENT_STATE_CHANGE:
                await self.js.publish(EVENT_STATE_CHANGE, json.dumps({
                    "type": "homeassistant.state_change",
                    "entity_id": entity_id,
                    "old_state": old_state,
                    "new_state": new_state,
                    "payload": event
                }).encode())
            
            logger.info(f"Emitted state change: {entity_id} {old_state} → {new_state}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting state change: {e}")
    
    async def emit_temperature_metric(self, entity_id: str, temperature: float):
        """Emit temperature as metric for anomaly detection"""
        try:
            await self.js.publish(METRICS_TEMPERATURE, json.dumps({
                "name": f"climate.{entity_id}",
                "value": temperature,
                "unit": "celsius",
                "timestamp": datetime.utcnow().isoformat(),
                "source": "homeassistant"
            }).encode())
            
            logger.debug(f"Emitted temperature metric: {entity_id} = {temperature}°C")
        
        except Exception as e:
            logger.error(f"Error emitting temperature metric: {e}")
    
    async def subscribe_capability_requests(self):
        """Subscribe to capability requests for HA operations"""
        try:
            sub = await self.nc.subscribe(call_subscribe_subject(self.service_name))
            logger.info("Subscribed to capability requests")
            
            async for msg in sub.messages:
                try:
                    capability = parse_capability_from_subject(msg.subject)
                    
                    request = json.loads(msg.data.decode())
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    result = await self.handle_capability(capability, params)
                    
                    await self.js.publish(reply_subject(request_id), json.dumps(result).encode())
                    
                    self.event_count += 1
                
                except Exception as e:
                    logger.error(f"Error processing capability: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle capability requests"""
        if capability == "event.home_assistant":
            return await self.get_events(params)
        elif capability == "state.device_update":
            return await self.update_device(params)
        elif capability == "climate.temperature":
            return await self.get_temperature(params)
        elif capability == "light.toggle":
            return await self.toggle_light(params)
        elif capability == "sensor.reading":
            return await self.get_sensor(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def get_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get recent Home Assistant events"""
        limit = params.get('limit', 10)
        
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "event.home_assistant",
            "events": list(self.tracked_entities.items())[:limit],
            "total_tracked": len(self.tracked_entities),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def update_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update device state"""
        entity_id = params.get('entity_id', '')
        try:
            validate_entity_id(entity_id)
        except ValueError:
            return {"error": "Invalid entity_id format", "entity_id": entity_id}
        new_state = params.get('state', '')
        
        if not self.session or not self.ha_token:
            return {
                "error": "HA not configured",
                "entity_id": entity_id
            }
        
        try:
            headers = {
                "Authorization": f"Bearer {self.ha_token}",
                "Content-Type": "application/json"
            }
            
            async with self.session.post(
                f"{self.ha_url}/api/states/{entity_id}",
                headers=headers,
                json={"state": new_state},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                success = resp.status == 200
                
                return {
                    "agent": self.service_name,
                    "capability": "state.device_update",
                    "entity_id": entity_id,
                    "new_state": new_state,
                    "success": success,
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        except Exception as e:
            logger.error(f"Error updating device: {e}")
            return {
                "error": str(e),
                "entity_id": entity_id
            }
    
    async def get_temperature(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get climate temperature reading"""
        entity_id = params.get('entity_id', '')
        
        if entity_id in self.tracked_entities:
            attrs = self.tracked_entities[entity_id].get('attributes', {})
            temperature = attrs.get('current_temperature', None)
            
            return {
                "agent": self.service_name,
                "capability": "climate.temperature",
                "entity_id": entity_id,
                "temperature": temperature,
                "unit": "celsius",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return {
            "error": f"Entity not found: {entity_id}",
            "entity_id": entity_id
        }
    
    async def toggle_light(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Toggle light on/off"""
        entity_id = params.get('entity_id', '')
        
        if entity_id in self.tracked_entities:
            current = self.tracked_entities[entity_id].get('state', 'off')
            new_state = 'off' if current == 'on' else 'on'
            
            # Attempt to update
            await self.update_device({"entity_id": entity_id, "state": new_state})
            
            return {
                "agent": self.service_name,
                "capability": "light.toggle",
                "entity_id": entity_id,
                "old_state": current,
                "new_state": new_state,
                "success": True,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return {
            "error": f"Light not found: {entity_id}",
            "entity_id": entity_id
        }
    
    async def get_sensor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get sensor reading"""
        entity_id = params.get('entity_id', '')
        
        if entity_id in self.tracked_entities:
            entity = self.tracked_entities[entity_id]
            
            return {
                "agent": self.service_name,
                "capability": "sensor.reading",
                "entity_id": entity_id,
                "state": entity.get('state'),
                "attributes": entity.get('attributes', {}),
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return {
            "error": f"Sensor not found: {entity_id}",
            "entity_id": entity_id
        }
    
    async def run(self):
        """Main emitter loop"""
        try:
            await self.connect()
            await self.register()
            
            logger.info("Home Assistant emitter started")
            
            await asyncio.gather(
                self.poll_states(),
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
    emitter = HomeAssistantEmitter()
    await emitter.run()


if __name__ == "__main__":
    asyncio.run(main())
