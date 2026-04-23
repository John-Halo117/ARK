#!/usr/bin/env python3
"""
Jellyfin Media Event Emitter - Monitors playback and library changes
Emits media events into ARK for processing
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any

import aiohttp
from ark.config import load_jellyfin_config
from ark.emitter_contracts import (
    build_jellyfin_playback_change_plan,
    build_jellyfin_playback_start_plans,
    build_jellyfin_playback_stop_plan,
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
    EVENT_MEDIA_PLAYBACK, METRICS_MEDIA_DURATION,
    call_subscribe_subject, reply_subject, parse_capability_from_subject,
)
from ark.time_utils import utc_now_iso

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('Jellyfin-Emitter')


class JellyfinEmitter:
    """Emits Jellyfin media events into ARK"""
    
    def __init__(self):
        config = load_jellyfin_config()
        self.service_name = "jellyfin"
        self.instance_id = config.runtime.instance_id
        self.nats_url = config.runtime.nats_url
        self.jellyfin_url = config.jellyfin_url
        self.jellyfin_token = config.jellyfin_token
        self.jellyfin_user_id = config.jellyfin_user_id
        
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
        self.gsb: GlobalStateBus = build_global_state_bus()
        self.audit = RuntimeAudit(
            self.gsb,
            source=EventSource.EMITTER_JELLYFIN.value,
            surface="emitter",
            default_tags={"emitter": self.service_name},
        )
        self.contracts = runtime_contract_registry()
        self.reducer_engine = ReducerEngine(
            (
                KeyedItemsReducer(
                    name="emitter.jellyfin.sessions",
                    key_field="session_id",
                    upsert_event="jellyfin.session_observed",
                    remove_event="jellyfin.session_removed",
                ),
            )
        )
        self.active_sessions: Dict[str, Any] = self.reducer_engine.view("emitter.jellyfin.sessions")["items"]
        self.dispatch = DispatchRegistry(
            (
                DispatchDescriptor("media.playback", self.get_playback_status),
                DispatchDescriptor("media.library", self.get_library),
                DispatchDescriptor("media.search", self.search_media),
                DispatchDescriptor("playback.status", self.get_playback_status),
                DispatchDescriptor("library.items", self.get_library_items),
            ),
            contracts=self.contracts,
        )
        
        logger.info(f"Jellyfin Emitter initialized (instance={self.instance_id})")
    
    async def connect(self):
        """Connect to NATS and create HTTP session"""
        if nats is None:
            raise RuntimeError("nats package is not installed")
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
                        self.reducer_engine.apply(
                            "jellyfin.session_observed",
                            {
                                "session_id": session_id,
                                "value": {
                                    "device_name": device_name,
                                    "item_id": item_id,
                                    "title": title,
                                    "media_type": media_type,
                                    "last_update": utc_now_iso(),
                                },
                            },
                        )
                    else:
                        # No active playback
                        if session_id in self.active_sessions:
                            # Playback stopped
                            await self.emit_playback_stop(session_id, device_name)
                            self.reducer_engine.apply(
                                "jellyfin.session_removed",
                                {"session_id": session_id},
                            )
                
                await asyncio.sleep(10)  # Poll every 10 seconds
            
            except Exception as e:
                logger.error(f"Playback monitor error: {e}")
                await asyncio.sleep(10)
    
    async def emit_playback_start(self, session_id: str, device: str, 
                                  title: str, media_type: str, item: Dict[str, Any]):
        """Emit playback start event"""
        try:
            plans = build_jellyfin_playback_start_plans(
                session_id=session_id,
                device=device,
                title=title,
                media_type=media_type,
                item=item,
                timestamp=utc_now_iso(),
            )
            for plan in plans:
                await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
            
            logger.info(f"Playback start: {device} → {title}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting playback start: {e}")
    
    async def emit_playback_change(self, session_id: str, device: str, 
                                   title: str, media_type: str, item: Dict[str, Any]):
        """Emit playback changed event"""
        try:
            plan = build_jellyfin_playback_change_plan(
                session_id=session_id,
                device=device,
                title=title,
                media_type=media_type,
                item=item,
                timestamp=utc_now_iso(),
            )
            await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
            
            logger.info(f"Playback changed: {device} → {title}")
            self.event_count += 1
        
        except Exception as e:
            logger.error(f"Error emitting playback change: {e}")
    
    async def emit_playback_stop(self, session_id: str, device: str):
        """Emit playback stop event"""
        try:
            plan = build_jellyfin_playback_stop_plan(
                session_id=session_id,
                device=device,
                timestamp=utc_now_iso(),
            )
            await self._publish_nats(self.js, plan.subject, plan.payload, plan.capability)
            
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
    
    async def get_playback_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current playback status"""
        return {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "playback.status",
            "active_sessions": len(self.active_sessions),
            "sessions": list(self.active_sessions.values()),
            "timestamp": utc_now_iso()
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
                        "timestamp": utc_now_iso()
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
                        "timestamp": utc_now_iso()
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
                        "timestamp": utc_now_iso()
                    }
                else:
                    return {"error": f"Jellyfin returned {resp.status}"}
        
        except Exception as e:
            logger.error(f"Error getting library items: {e}")
            return {"error": str(e)}

    async def _publish_nats(self, target: Any, subject: str, payload: Dict[str, Any], capability: str) -> None:
        await self.audit.publish_json(target, subject, payload, capability)
    
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
