"""
Typed runtime configuration for ARK Python services.
Centralizes environment parsing, defaulting, and validation.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _read_env(name: str, default: str = "", max_len: int = 2048) -> str:
    raw = os.environ.get(name, default)
    if raw is None:
        return default
    value = str(raw).strip()
    return value[:max_len]


def _validate_url(value: str, default: str, *, allowed_schemes: tuple[str, ...]) -> str:
    parsed = urlparse(value)
    if parsed.scheme in allowed_schemes and parsed.netloc:
        return value
    return default


def _load_instance_id() -> str:
    configured = _read_env("INSTANCE_ID", "")
    if configured and _INSTANCE_ID_RE.fullmatch(configured):
        return configured
    return str(uuid.uuid4())[:12]


@dataclass(frozen=True)
class ServiceRuntimeConfig:
    instance_id: str
    nats_url: str


@dataclass(frozen=True)
class GatewayConfig:
    nats_url: str
    mesh_url: str


@dataclass(frozen=True)
class ComposioConfig:
    runtime: ServiceRuntimeConfig
    composio_api_key: str


@dataclass(frozen=True)
class HomeAssistantConfig:
    runtime: ServiceRuntimeConfig
    ha_url: str
    ha_token: str


@dataclass(frozen=True)
class JellyfinConfig:
    runtime: ServiceRuntimeConfig
    jellyfin_url: str
    jellyfin_token: str
    jellyfin_user_id: str


@dataclass(frozen=True)
class UniFiConfig:
    runtime: ServiceRuntimeConfig
    unifi_url: str
    unifi_username: str
    unifi_password: str
    unifi_site: str
    unifi_ca_bundle: str


def load_service_runtime_config() -> ServiceRuntimeConfig:
    nats_url = _validate_url(
        _read_env("NATS_URL", "nats://nats:4222"),
        "nats://nats:4222",
        allowed_schemes=("nats", "tls", "ws", "wss"),
    )
    return ServiceRuntimeConfig(
        instance_id=_load_instance_id(),
        nats_url=nats_url,
    )


def load_gateway_config() -> GatewayConfig:
    nats_url = _validate_url(
        _read_env("NATS_URL", "nats://nats:4222"),
        "nats://nats:4222",
        allowed_schemes=("nats", "tls", "ws", "wss"),
    )
    mesh_url = _validate_url(
        _read_env("MESH_URL", "http://ark-mesh:7000"),
        "http://ark-mesh:7000",
        allowed_schemes=("http", "https"),
    )
    return GatewayConfig(nats_url=nats_url, mesh_url=mesh_url)


def load_composio_config() -> ComposioConfig:
    return ComposioConfig(
        runtime=load_service_runtime_config(),
        composio_api_key=_read_env("COMPOSIO_API_KEY", "", max_len=8192),
    )


def load_homeassistant_config() -> HomeAssistantConfig:
    ha_url = _validate_url(
        _read_env("HA_URL", "http://homeassistant:8123"),
        "http://homeassistant:8123",
        allowed_schemes=("http", "https"),
    )
    return HomeAssistantConfig(
        runtime=load_service_runtime_config(),
        ha_url=ha_url,
        ha_token=_read_env("HA_TOKEN", "", max_len=8192),
    )


def load_jellyfin_config() -> JellyfinConfig:
    jellyfin_url = _validate_url(
        _read_env("JELLYFIN_URL", "http://jellyfin:8096"),
        "http://jellyfin:8096",
        allowed_schemes=("http", "https"),
    )
    return JellyfinConfig(
        runtime=load_service_runtime_config(),
        jellyfin_url=jellyfin_url,
        jellyfin_token=_read_env("JELLYFIN_TOKEN", "", max_len=8192),
        jellyfin_user_id=_read_env("JELLYFIN_USER_ID", "", max_len=256),
    )


def load_unifi_config() -> UniFiConfig:
    unifi_url = _validate_url(
        _read_env("UNIFI_URL", "https://unifi:8443"),
        "https://unifi:8443",
        allowed_schemes=("https",),
    )
    return UniFiConfig(
        runtime=load_service_runtime_config(),
        unifi_url=unifi_url,
        unifi_username=_read_env("UNIFI_USERNAME", "", max_len=256),
        unifi_password=_read_env("UNIFI_PASSWORD", "", max_len=2048),
        unifi_site=_read_env("UNIFI_SITE", "default", max_len=128),
        unifi_ca_bundle=_read_env("UNIFI_CA_BUNDLE", "", max_len=1024),
    )
