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
class IntegrationConfig:
    web_fetch_timeout_s: int
    web_fetch_max_bytes: int
    web_search_url: str
    web_search_timeout_s: int
    web_search_max_results: int
    maps_geocode_url: str
    maps_timeout_s: int
    docker_cli: str
    docker_timeout_s: int


@dataclass(frozen=True)
class GlobalStateBusConfig:
    enabled: bool
    max_payload_bytes: int
    max_tag_count: int
    default_source: str


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


def load_integration_config() -> IntegrationConfig:
    return IntegrationConfig(
        web_fetch_timeout_s=_read_int_env("ARK_WEB_FETCH_TIMEOUT_S", 5, minimum=1, maximum=30),
        web_fetch_max_bytes=_read_int_env("ARK_WEB_FETCH_MAX_BYTES", 131_072, minimum=1024, maximum=1_048_576),
        web_search_url=_validate_url(
            _read_env("ARK_WEB_SEARCH_URL", ""),
            "",
            allowed_schemes=("http", "https"),
        ),
        web_search_timeout_s=_read_int_env("ARK_WEB_SEARCH_TIMEOUT_S", 5, minimum=1, maximum=30),
        web_search_max_results=_read_int_env("ARK_WEB_SEARCH_MAX_RESULTS", 5, minimum=1, maximum=10),
        maps_geocode_url=_validate_url(
            _read_env("ARK_MAPS_GEOCODE_URL", ""),
            "",
            allowed_schemes=("http", "https"),
        ),
        maps_timeout_s=_read_int_env("ARK_MAPS_TIMEOUT_S", 5, minimum=1, maximum=30),
        docker_cli=_read_env("ARK_DOCKER_CLI", "docker", max_len=128),
        docker_timeout_s=_read_int_env("ARK_DOCKER_TIMEOUT_S", 3, minimum=1, maximum=15),
    )


def load_global_state_bus_config() -> GlobalStateBusConfig:
    return GlobalStateBusConfig(
        enabled=_read_bool_env("ARK_GSB_ENABLED", True),
        max_payload_bytes=_read_int_env("ARK_GSB_MAX_PAYLOAD_BYTES", 1_048_576, minimum=1024, maximum=4_194_304),
        max_tag_count=_read_int_env("ARK_GSB_MAX_TAG_COUNT", 32, minimum=1, maximum=64),
        default_source=_read_env("ARK_GSB_DEFAULT_SOURCE", "ark.core", max_len=128),
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


def _read_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _read_env(name, str(default), max_len=32)
    try:
        value = int(raw)
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _read_bool_env(name: str, default: bool) -> bool:
    raw = _read_env(name, "1" if default else "0", max_len=16).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default
