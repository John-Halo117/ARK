"""
ARK NATS Subject Constants — single source of truth for all topic names.

Convention:
    ark.<domain>.<action>[.<qualifier>]

Domains:
    mesh     — service registration & discovery
    call     — capability invocation  (ark.call.<service>.<capability>)
    reply    — request responses      (ark.reply.<request_id>)
    event    — domain events          (ark.event.<category>.<detail>)
    metrics  — telemetry              (ark.metrics.<name>)
    anomaly  — anomaly signals
    system   — autoscaler signals     (ark.system.<signal>.<service>)
    spawn    — scaling lifecycle

All subjects use lowercase, dot-delimited tokens.
Wildcards: '*' matches one token, '>' matches one-or-more trailing tokens.
"""

# ---------------------------------------------------------------------------
# Mesh — registration & discovery
# ---------------------------------------------------------------------------
MESH_REGISTER = "ark.mesh.register"
MESH_HEARTBEAT = "ark.mesh.heartbeat"
MESH_REGISTERED = "ark.mesh.registered"  # confirmation broadcast

# ---------------------------------------------------------------------------
# Capability call / reply
# ---------------------------------------------------------------------------


def call_subject(service: str, capability: str) -> str:
    """Build ``ark.call.<service>.<capability>`` subject."""
    return f"ark.call.{service}.{capability}"


def call_subscribe_subject(service: str) -> str:
    """Subscribe pattern for all capabilities of a service (multi-token)."""
    return f"ark.call.{service}.>"


def reply_subject(request_id: str) -> str:
    """Build ``ark.reply.<request_id>`` subject."""
    return f"ark.reply.{request_id}"


# ---------------------------------------------------------------------------
# Events — domain events emitted by emitters / agents
# ---------------------------------------------------------------------------
EVENT_STATE_CHANGE = "ark.event.state.change"
EVENT_CLIMATE_TEMPERATURE = "ark.event.climate.temperature"
EVENT_LIGHT_TOGGLE = "ark.event.light.toggle"
EVENT_SENSOR_READING = "ark.event.sensor.reading"
EVENT_MEDIA_PLAYBACK = "ark.event.media.playback"
EVENT_NETWORK_DEVICE = "ark.event.network.device"

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
METRICS_TEMPERATURE = "ark.metrics.temperature"
METRICS_MEDIA_DURATION = "ark.metrics.media_duration"
METRICS_NETWORK = "ark.metrics.network"
METRICS_SUBSCRIBE = "ark.metrics.>"  # multi-token wildcard

# ---------------------------------------------------------------------------
# Anomaly
# ---------------------------------------------------------------------------
ANOMALY_DETECTED = "ark.anomaly.detected"

# ---------------------------------------------------------------------------
# System — autoscaler demand / latency / health signals
# ---------------------------------------------------------------------------
SYSTEM_QUEUE_DEPTH_SUBSCRIBE = "ark.system.queue_depth.*"
SYSTEM_LATENCY_SUBSCRIBE = "ark.system.latency.*"
SYSTEM_ASHI = "ark.system.ashi"

# ---------------------------------------------------------------------------
# Spawn lifecycle
# ---------------------------------------------------------------------------
SPAWN_CONFIRMED = "ark.spawn.confirmed"

# ---------------------------------------------------------------------------
# Ingestion / CID event backbone
# ---------------------------------------------------------------------------
# Canonical CID events produced by the single-writer ingestion leader.
EVENTS_CID = "ark.events.cid"

# JetStream name that persists EVENTS_CID messages.
EVENTS_STREAM = "ARK_EVENTS"


def parse_capability_from_subject(subject: str) -> str:
    """Extract the dotted capability name from a ``ark.call.<svc>.<cap>`` subject.

    >>> parse_capability_from_subject("ark.call.opencode.code.analyze")
    'code.analyze'
    >>> parse_capability_from_subject("ark.call.composio.external.email")
    'external.email'
    """
    parts = subject.split(".")
    return ".".join(parts[3:]) if len(parts) > 3 else "unknown"


def parse_service_from_queue_depth(subject: str) -> str:
    """Extract service name from ``ark.system.queue_depth.<service>``."""
    parts = subject.split(".")
    return parts[-1] if len(parts) > 3 else "unknown"
