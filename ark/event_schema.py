"""
Unified event schema for ARK system
Used across Python (agents, emitters) and Rust (analysis engine)
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from enum import Enum
import json
from datetime import datetime


class EventSource(str, Enum):
    """Event origin"""
    EMITTER_HA = "emitter.homeassistant"
    EMITTER_JELLYFIN = "emitter.jellyfin"
    EMITTER_UNIFI = "emitter.unifi"
    AGENT_OPENCODE = "agent.opencode"
    AGENT_OPENWOLF = "agent.openwolf"
    AGENT_COMPOSIO = "agent.composio"
    ARK_CORE = "ark.core"
    SYSTEM = "system"


class EventType(str, Enum):
    """Event classification"""
    METRIC = "metric"
    STATE = "state"
    ANOMALY = "anomaly"
    DECISION = "decision"
    ERROR = "error"
    STATUS = "status"


@dataclass
class LKS:
    """TRISCA metrics (from Rust)"""
    qts: float
    dsi: float
    dss: float
    dss_kalman: float
    phase: str  # stable, drift, unstable, critical

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'LKS':
        return LKS(**d)


@dataclass
class ArkEvent:
    """Universal event for ARK system"""
    # Core
    event_id: str
    event_type: EventType
    source: EventSource
    timestamp: int  # Unix timestamp (seconds)
    
    # Content
    payload: Dict[str, Any]
    
    # Optional analysis (populated by ARK core)
    lks: Optional[LKS] = None
    decision: Optional[str] = None
    delta: Optional[Dict[str, float]] = None
    
    # Metadata
    tags: Dict[str, str] = None
    
    def to_json(self) -> str:
        data = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source.value,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "lks": self.lks.to_dict() if self.lks else None,
            "decision": self.decision,
            "delta": self.delta,
            "tags": self.tags or {}
        }
        return json.dumps(data)
    
    @staticmethod
    def from_json(data: str) -> 'ArkEvent':
        d = json.loads(data)
        lks = LKS.from_dict(d['lks']) if d.get('lks') else None
        return ArkEvent(
            event_id=d['event_id'],
            event_type=EventType(d['event_type']),
            source=EventSource(d['source']),
            timestamp=d['timestamp'],
            payload=d['payload'],
            lks=lks,
            decision=d.get('decision'),
            delta=d.get('delta'),
            tags=d.get('tags', {})
        )


def create_event(
    event_type: EventType,
    source: EventSource,
    payload: Dict[str, Any],
    event_id: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None
) -> ArkEvent:
    """Factory for creating events"""
    import uuid
    return ArkEvent(
        event_id=event_id or str(uuid.uuid4())[:12],
        event_type=event_type,
        source=source,
        timestamp=int(datetime.utcnow().timestamp()),
        payload=payload,
        tags=tags or {}
    )
