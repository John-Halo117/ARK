"""
Unified event schema for ARK system
Used across Python (agents, emitters) and Rust (analysis engine)
Hardened: field validation, payload size limits, safe serialisation.
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


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES: int = 1_048_576  # 1 MiB
MAX_EVENT_ID_LEN: int = 128
MAX_TAG_COUNT: int = 64
MAX_TAG_KEY_LEN: int = 128
MAX_TAG_VALUE_LEN: int = 512
ALLOWED_PHASES = frozenset({"stable", "drift", "unstable", "critical"})


def validate_payload(payload: Any, max_bytes: int = MAX_PAYLOAD_BYTES) -> Dict[str, Any]:
    """Ensure payload is a dict within size budget."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    raw = json.dumps(payload, default=str)
    if len(raw.encode()) > max_bytes:
        raise ValueError(f"payload exceeds {max_bytes} bytes")
    return payload


def validate_tags(tags: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Validate and clamp tags dict."""
    if tags is None:
        return {}
    if not isinstance(tags, dict):
        raise ValueError("tags must be a dict")
    if len(tags) > MAX_TAG_COUNT:
        raise ValueError(f"Too many tags (max {MAX_TAG_COUNT})")
    out: Dict[str, str] = {}
    for k, v in tags.items():
        k_str = str(k)[:MAX_TAG_KEY_LEN]
        v_str = str(v)[:MAX_TAG_VALUE_LEN]
        out[k_str] = v_str
    return out


def validate_lks_phase(phase: str) -> str:
    """Validate LKS phase value."""
    if phase not in ALLOWED_PHASES:
        raise ValueError(f"Invalid LKS phase: {phase!r}; allowed: {ALLOWED_PHASES}")
    return phase


def create_event(
    event_type: EventType,
    source: EventSource,
    payload: Dict[str, Any],
    event_id: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None
) -> ArkEvent:
    """Factory for creating events with validation."""
    import uuid
    payload = validate_payload(payload)
    tags = validate_tags(tags)
    eid = event_id or str(uuid.uuid4())[:12]
    if len(eid) > MAX_EVENT_ID_LEN:
        raise ValueError(f"event_id too long (max {MAX_EVENT_ID_LEN})")
    return ArkEvent(
        event_id=eid,
        event_type=event_type,
        source=source,
        timestamp=int(datetime.utcnow().timestamp()),
        payload=payload,
        tags=tags
    )
