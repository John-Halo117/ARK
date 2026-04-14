"""
ARK Security Module — hardened input validation, sanitization, rate limiting,
authentication middleware, and secure HTTP headers.

All public helpers are intentionally pure functions or lightweight classes so
they can be used across the gateway, agents, and emitters without pulling in
heavy framework dependencies.
"""

import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from aiohttp import web

logger = logging.getLogger("ARK-Security")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES: int = 1_048_576  # 1 MiB
MAX_STRING_LEN: int = 10_000
MAX_EVENT_ID_LEN: int = 128
MAX_TAG_COUNT: int = 64
MAX_TAG_KEY_LEN: int = 128
MAX_TAG_VALUE_LEN: int = 512
ALLOWED_PHASES: Set[str] = {"stable", "drift", "unstable", "critical"}
NATS_SUBJECT_RE = re.compile(r"^[a-zA-Z0-9._*>-]+$")
ENTITY_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,256}$")
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
INSTANCE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")

# Secrets — read once at import time, never logged
_API_TOKEN: str = os.environ.get("ARK_API_TOKEN", "")
_API_TOKENS: Set[str] = set(
    filter(None, os.environ.get("ARK_API_TOKENS", "").split(","))
)
if _API_TOKEN:
    _API_TOKENS.add(_API_TOKEN)

# ---------------------------------------------------------------------------
# Sanitisation helpers
# ---------------------------------------------------------------------------


def sanitize_string(value: str, max_len: int = MAX_STRING_LEN) -> str:
    """Strip control characters and clamp length."""
    if not isinstance(value, str):
        raise ValueError("Expected a string value")
    # Remove ASCII control chars except newline/tab
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return cleaned[:max_len]


def sanitize_html(value: str, max_len: int = MAX_STRING_LEN) -> str:
    """HTML-escape and clamp."""
    return html.escape(sanitize_string(value, max_len))


def sanitize_nats_subject(subject: str) -> str:
    """Validate and return a safe NATS subject, or raise."""
    subject = subject.strip()
    if not NATS_SUBJECT_RE.match(subject):
        raise ValueError(f"Invalid NATS subject: {subject!r}")
    if len(subject) > 256:
        raise ValueError("NATS subject too long (max 256)")
    return subject


def sanitize_dict_keys(d: Dict[str, Any], allowed: Set[str]) -> Dict[str, Any]:
    """Return a copy keeping only *allowed* keys."""
    return {k: v for k, v in d.items() if k in allowed}


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def validate_event_id(event_id: str) -> str:
    """Validate an event ID."""
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")
    if len(event_id) > MAX_EVENT_ID_LEN:
        raise ValueError(f"event_id too long (max {MAX_EVENT_ID_LEN})")
    return sanitize_string(event_id, MAX_EVENT_ID_LEN)


def validate_service_name(name: str) -> str:
    if not SERVICE_NAME_RE.match(name):
        raise ValueError(f"Invalid service name: {name!r}")
    return name


def validate_instance_id(iid: str) -> str:
    if not INSTANCE_ID_RE.match(iid):
        raise ValueError(f"Invalid instance ID: {iid!r}")
    return iid


def validate_capability(cap: str) -> str:
    if not CAPABILITY_RE.match(cap):
        raise ValueError(f"Invalid capability: {cap!r}")
    return cap


def validate_entity_id(entity_id: str) -> str:
    if not ENTITY_ID_RE.match(entity_id):
        raise ValueError(f"Invalid entity ID: {entity_id!r}")
    return entity_id


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
        k = sanitize_string(str(k), MAX_TAG_KEY_LEN)
        v = sanitize_string(str(v), MAX_TAG_VALUE_LEN)
        out[k] = v
    return out


def validate_payload(payload: Any, max_bytes: int = MAX_PAYLOAD_BYTES) -> Dict[str, Any]:
    """Ensure payload is a dict and within size budget."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    import json
    raw = json.dumps(payload, default=str)
    if len(raw.encode()) > max_bytes:
        raise ValueError(f"payload exceeds {max_bytes} bytes")
    return payload


def validate_lks_phase(phase: str) -> str:
    if phase not in ALLOWED_PHASES:
        raise ValueError(f"Invalid LKS phase: {phase!r}; allowed: {ALLOWED_PHASES}")
    return phase


def validate_positive_int(value: Any, name: str = "value", max_val: int = 10_000) -> int:
    """Coerce to int and enforce bounds."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if v < 0:
        raise ValueError(f"{name} must be >= 0")
    if v > max_val:
        v = max_val
    return v


def clamp_limit(limit: Any, default: int = 100, ceiling: int = 10_000) -> int:
    """Safe limit for DB queries — no f-string injection possible."""
    try:
        v = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(v, ceiling))


# ---------------------------------------------------------------------------
# Rate limiter (in-process, token-bucket)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple per-key token-bucket rate limiter.

    Args:
        rate: refill tokens per second
        burst: maximum bucket size
    """

    def __init__(self, rate: float = 10.0, burst: int = 50):
        self._rate = rate
        self._burst = burst
        self._buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def allow(self, key: str = "__global__") -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self._burst), now))
        elapsed = now - last
        tokens = min(self._burst, tokens + elapsed * self._rate)
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True
        self._buckets[key] = (tokens, now)
        return False

    def reset(self, key: str = "__global__") -> None:
        self._buckets.pop(key, None)


# Global limiters — importable by gateway / mesh / autoscaler
api_rate_limiter = RateLimiter(rate=20.0, burst=100)
registration_rate_limiter = RateLimiter(rate=5.0, burst=20)


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison."""
    return hmac.compare_digest(a.encode(), b.encode())


def verify_bearer_token(auth_header: Optional[str]) -> bool:
    """Check *Authorization: Bearer <token>* against configured tokens."""
    if not _API_TOKENS:
        return True  # auth disabled when no tokens configured
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    token = parts[1].strip()
    return any(constant_time_compare(token, t) for t in _API_TOKENS)


def generate_api_token(nbytes: int = 32) -> str:
    """Generate a cryptographically-random URL-safe token."""
    return secrets.token_urlsafe(nbytes)


# ---------------------------------------------------------------------------
# aiohttp middleware
# ---------------------------------------------------------------------------


@web.middleware
async def auth_middleware(request: web.Request, handler: Callable) -> web.Response:
    """Reject unauthenticated requests when tokens are configured."""
    if _API_TOKENS:
        if not verify_bearer_token(request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


@web.middleware
async def rate_limit_middleware(request: web.Request, handler: Callable) -> web.Response:
    """Per-IP rate limiting."""
    ip = request.remote or "unknown"
    if not api_rate_limiter.allow(ip):
        logger.warning("Rate limit exceeded for %s", ip)
        return web.json_response({"error": "rate limit exceeded"}, status=429)
    return await handler(request)


@web.middleware
async def secure_headers_middleware(request: web.Request, handler: Callable) -> web.Response:
    """Attach security headers to every response."""
    resp: web.Response = await handler(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Strip server identification
    resp.headers.pop("Server", None)
    return resp


@web.middleware
async def error_shield_middleware(request: web.Request, handler: Callable) -> web.Response:
    """Catch unhandled exceptions and return a generic 500 without leaking internals."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise  # let aiohttp handle HTTP errors normally
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        return web.json_response(
            {"error": "internal server error"},
            status=500,
        )


@web.middleware
async def request_id_middleware(request: web.Request, handler: Callable) -> web.Response:
    """Attach a unique request ID for tracing."""
    rid = request.headers.get("X-Request-ID") or secrets.token_hex(8)
    request["request_id"] = rid
    resp: web.Response = await handler(request)
    resp.headers["X-Request-ID"] = rid
    return resp


# ---------------------------------------------------------------------------
# Logging sanitiser
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization", "cookie"}


def redact_dict(d: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """Return a shallow copy of *d* with sensitive values masked."""
    if depth > 5:
        return {"__redacted__": "depth limit"}
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = "***REDACTED***"
        elif isinstance(v, dict):
            out[k] = redact_dict(v, depth + 1)
        else:
            out[k] = v
    return out


def safe_log_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare an event dict for logging — redact secrets, truncate large payloads."""
    redacted = redact_dict(event)
    payload = redacted.get("payload")
    if isinstance(payload, dict):
        import json
        raw = json.dumps(payload, default=str)
        if len(raw) > 2048:
            redacted["payload"] = {"__truncated__": True, "size": len(raw)}
    return redacted


# ---------------------------------------------------------------------------
# Subprocess hardening
# ---------------------------------------------------------------------------

_SAFE_CMD_RE = re.compile(r"^[a-zA-Z0-9_.=/:@-]+$")


def validate_docker_arg(arg: str) -> str:
    """Reject shell-metachar-laden docker arguments."""
    if not _SAFE_CMD_RE.match(arg):
        raise ValueError(f"Unsafe docker argument: {arg!r}")
    return arg


def build_safe_docker_cmd(
    image: str,
    container_name: str,
    cpu_limit: str,
    memory_limit: str,
    env: Dict[str, str],
    network: str = "ark-net",
) -> List[str]:
    """Build a docker-run command list with every argument validated."""
    validate_docker_arg(image)
    validate_docker_arg(container_name)
    validate_docker_arg(cpu_limit)
    validate_docker_arg(memory_limit)
    validate_docker_arg(network)

    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        f"--cpus={cpu_limit}",
        f"--memory={memory_limit}",
        "--network", network,
        "--read-only",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "--pids-limit", "256",
    ]
    for k, v in env.items():
        validate_docker_arg(k)
        validate_docker_arg(v)
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    return cmd
