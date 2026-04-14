#!/usr/bin/env python3
"""
Jellyfin Media Event Emitter - Monitors playback and library changes
Emits media events into ARK for processing
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

from ark.subjects import (
    MESH_REGISTER, MESH_HEARTBEAT,
    EVENT_MEDIA_PLAYBACK, METRICS_MEDIA_DURATION,
    call_subscribe_subject, reply_subject, parse_capability_from_subject,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('Jellyfin-Emitter')


class JellyfinEmitter:
    """Emits Jellyfin media events into ARK"""
    
    def __init__(self):
        self.service_name = "jellyfin"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        self.jellyfin_url = os.environ.get('JELLYFIN_URL', 'http://jellyfin:8096')
        self.jellyfin_token = os.environ.get('JELLYFIN_TOKEN', '')
        self.jellyfin_user_id = os.environ.get('JELLYFIN_USER_ID', '')
        
        self.capabilities = [
            "media.playback",
            "media.library",
            "media.search",
            "playback.status",
            "library.items"
        ]
        
        self.nc = None
        self.js = None
        self.session = None
        self.event_count = 0
        self.active_sessions: Dict[str, Any] = {}
        
        logger.info(f"Jellyfin Emitter initialized (instance={self.instance_id})")
    
    async def connect(self):
        """Connect to NATS and create HTTP session"""
        try:
            self.nc = await nats.connect(self.nats_url)
            self.js = self.nc.jetstream()
            self.session = aiohttp.ClientSession()
            logger.info(f"Connected to NATS and Jellyfin at {self.jellyfin_url}")
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
                "jellyfin_url": self.jellyfin_url,
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
    
    async def poll_sessions(self):
        """Poll Jellyfin for active playback sessions"""
        if not self.session or not self.jellyfin_token:
            logger.warning("Jellyfin session or token not configured")
            return []
        
        try:
            params = {"api_key": self.jellyfin_token}
            
            async with self.session.get(
                f"{self.jellyfin_url}/Sessions",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    sessions = await resp.json()
                    return sessions
                else:
                    logger.warning(f"Jellyfin API returned {resp.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error fetching sessions: {e}")
            return []
    
    async def monitor_playback(self):
        """Monitor active playback sessions and emit events"""
        while True:
            try:
                sessions = await self.poll_sessions()
                
                for session in sessions:
                    session_id = session.get('Id', '')
                    device_name = session.get('DeviceName', 'unknown')
                    now_playing = session.get('NowPlayingItem', {})
                    is_active = session.get('IsActive', False)
                    
                    if now_playing and is_active:
                        # Playback is happening
                        item_id = now_playing.get('Id', '')
                        title = now_playing.get('Name', 'Unknown')
                        media_type = now_playing.get('Type', 'unknown')
                        
                        # Check if this is new or changed
                        if session_id in self.active_sessions:
                            prev = self.active_sessions[session_id]
                            if prev.get('item_id') != item_id:
                                # Different item now playing
                                await self.emit_playback_change(
                                    session_id, device_name, title, media_type, now_playing
                                )
                        else:
                            # New playback session
                            await self.emit_playback_start(
                                session_id, device_name, title, media_type, now_playing
                            )
                        
                        # Update tracked session
                        self.active_sessions[session_id] = {
                            "device_name": device_name,
                            "item_id": item_id,
                            "title": title,
                            "media_type": media_type,
                            "last_update": datetime.utcnow().isoformat()
                        }
                    else:
                        # No active playback
                        if session_id in self.active_sessions:
                            # Playback stopped
                            await self.emit_playback_stop(session_id, device_name)
                            del self.active_sessions[session_id]
                
                await asyncio.sleep(10)  # Poll every 10 seconds
            
            except Exception as e:
                logger.error(f"Playback monitor error: {e}")
                await asyncio.sleep(10)
    
    async def emit_playback_start(self, session_id: str, device: str, 
                                  title: str, media_type: str, item: Dict[str, Any]):
        """Emit playback start event"""
        try:
            event = {
                "event": "playback_start",
                "session_id": session_id,
                "device": device,
                "title": title,
                "media_type": media_type,
                "item": item,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "jellyfin"
            }
            
            await self.js.publish(EVENT_MEDIA_PLAYBACK, json.dumps(event).encode())
            
            # Also emit metric for duration if available
            duration = item.get('RunTimeTicks', 0)
            if duration:
                await self.js.publish(METRICS_MEDIA_DURATION, json.dumps({
                    "name": f"media.{media_type}",
                    "value": duration / 10000000,  # Convert ticks to seconds
                    "unit": "seconds",
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
            
            logger.info(f"Playback start: {device} → {title}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting playback start: {e}")
    
    async def emit_playback_change(self, session_id: str, device: str, 
                                   title: str, media_type: str, item: Dict[str, Any]):
        """Emit playback changed event"""
        try:
            event = {
                "event": "playback_changed",
                "session_id": session_id,
                "device": device,
                "title": title,
                "media_type": media_type,
                "item": item,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "jellyfin"
            }
            
            await self.js.publish(EVENT_MEDIA_PLAYBACK, json.dumps(event).encode())
            
            logger.info(f"Playback changed: {device} → {title}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting playback change: {e}")
    
    async def emit_playback_stop(self, session_id: str, device: str):
        """Emit playback stop event"""
        try:
            event = {
                "event": "playback_stop",
                "session_id": session_id,
                "device": device,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "jellyfin"
            }
            
            await self.js.publish(EVENT_MEDIA_PLAYBACK, json.dumps(event).encode())
            
            logger.info(f"Playback stopped: {device}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting playback stop: {e}")
    
    async def subscribe_capability_requests(self):
        """Subscribe to capability requests for Jellyfin operations"""
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
        if capability == "media.playback":
            return await self.get_playback_status(params)
        elif capability == "media.library":
            return await self.get_library(params)
        elif capability == "media.search":
            return await self.search_media(params)
        elif capability == "playback.status":
            return await self.get_playback_status(params)
        elif capability == "library.items":
            return await self.get_library_items(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def get_playback_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current playback status"""
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "playback.status",
            "active_sessions": len(self.active_sessions),
            "sessions": list(self.active_sessions.values()),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def get_library(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get library information"""
        if not self.session or not self.jellyfin_token:
            return {"error": "Jellyfin not configured"}
        
        try:
            params_dict = {"api_key": self.jellyfin_token}
            
            async with self.session.get(
                f"{self.jellyfin_url}/Library/MediaFolders",
                params=params_dict,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    folders = await resp.json()
                    
                    return {
                        "agent": self.service_name,
                        "capability": "media.library",
                        "folders": folders.get('Items', []),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                else:
                    return {"error": f"Jellyfin returned {resp.status}"}
        
        except Exception as e:
            logger.error(f"Error getting library: {e}")
            return {"error": str(e)}
    
    async def search_media(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search media library"""
        query = params.get('query', '')
        
        if not self.session or not self.jellyfin_token:
            return {"error": "Jellyfin not configured"}
        
        try:
            api_params = {
                "api_key": self.jellyfin_token,
                "searchTerm": query,
                "limit": 20
            }
            
            async with self.session.get(
                f"{self.jellyfin_url}/Search/Hints",
                params=api_params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    
                    return {
                        "agent": self.service_name,
                        "capability": "media.search",
                        "query": query,
                        "results": results.get('SearchHints', []),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                else:
                    return {"error": f"Jellyfin returned {resp.status}"}
        
        except Exception as e:
            logger.error(f"Error searching media: {e}")
            return {"error": str(e)}
    
    async def get_library_items(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get library items"""
        if not self.session or not self.jellyfin_token:
            return {"error": "Jellyfin not configured"}
        
        try:
            api_params = {
                "api_key": self.jellyfin_token,
                "limit": 50
            }
            
            async with self.session.get(
                f"{self.jellyfin_url}/Users/{self.jellyfin_user_id}/Items",
                params=api_params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    items = await resp.json()
                    
                    return {
                        "agent": self.service_name,
                        "capability": "library.items",
                        "items": items.get('Items', []),
                        "total": items.get('TotalRecordCount', 0),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                else:
                    return {"error": f"Jellyfin returned {resp.status}"}
        
        except Exception as e:
            logger.error(f"Error getting library items: {e}")
            return {"error": str(e)}
    
    async def run(self):
        """Main emitter loop"""
        try:
            await self.connect()
            await self.register()
            
            logger.info("Jellyfin emitter started")
            
            await asyncio.gather(
                self.monitor_playback(),
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
    emitter = JellyfinEmitter()
    await emitter.run()


if __name__ == "__main__":
    asyncio.run(main())
