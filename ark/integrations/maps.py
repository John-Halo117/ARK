"""Local-first maps integration adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ark.config import IntegrationConfig
from ark.math_utils import haversine_km, safe_float, valid_lat, valid_lon
from ark.security import sanitize_string

from .contracts import IntegrationHealth, IntegrationRequest, IntegrationResult, failure, success
from .http import append_query, fetch_json


@dataclass(frozen=True)
class MapsGeocodeAdapter:
    config: IntegrationConfig
    capability: str = "external.maps.geocode"

    def health(self) -> IntegrationHealth:
        ok = bool(self.config.maps_geocode_url)
        detail = "local geocoder configured" if ok else "set ARK_MAPS_GEOCODE_URL"
        return IntegrationHealth(self.capability, ok, detail)

    def execute(self, request: IntegrationRequest) -> IntegrationResult:
        if not self.config.maps_geocode_url:
            return failure(self.capability, "MAPS_GEOCODE_UNCONFIGURED", "set ARK_MAPS_GEOCODE_URL")
        query = sanitize_string(str(request.params.get("query", "")), 512)
        if not query:
            return failure(self.capability, "MAPS_GEOCODE_MISSING_QUERY", "query is required")
        try:
            payload = fetch_json(
                _geocode_url(self.config.maps_geocode_url, query),
                timeout_s=self.config.maps_timeout_s,
                max_bytes=self.config.web_fetch_max_bytes,
            )
        except (OSError, ValueError) as exc:
            return failure(self.capability, "MAPS_GEOCODE_FAILED", str(exc), context={"query": query})
        return success(self.capability, {"query": query, "results": _normalize_places(payload)})


@dataclass(frozen=True)
class MapsDistanceAdapter:
    capability: str = "external.maps.distance"

    def health(self) -> IntegrationHealth:
        return IntegrationHealth(self.capability, True, "offline coordinate distance ready")

    def execute(self, request: IntegrationRequest) -> IntegrationResult:
        parsed = _parse_points(request.params)
        if isinstance(parsed, IntegrationResult):
            return parsed
        distance_km = haversine_km(*parsed)
        return success(
            self.capability,
            {
                "distance_km": round(distance_km, 4),
                "distance_mi": round(distance_km * 0.621371, 4),
            },
        )


def _geocode_url(base_url: str, query: str) -> str:
    if "{query}" in base_url:
        return base_url.replace("{query}", query)
    return append_query(base_url, {"q": query, "format": "json"})


def _normalize_places(payload: object) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else [payload]
    return [_normalize_place(row) for row in rows[:5] if isinstance(row, dict)]


def _normalize_place(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": sanitize_string(str(row.get("display_name", row.get("label", ""))), 512),
        "lat": safe_float(row.get("lat")),
        "lon": safe_float(row.get("lon", row.get("lng"))),
    }


def _parse_points(params: dict[str, Any]) -> tuple[float, float, float, float] | IntegrationResult:
    try:
        lat1 = float(params["lat1"])
        lon1 = float(params["lon1"])
        lat2 = float(params["lat2"])
        lon2 = float(params["lon2"])
    except (KeyError, TypeError, ValueError):
        return failure("external.maps.distance", "MAPS_DISTANCE_BAD_INPUT", "lat1/lon1/lat2/lon2 are required")
    if not all((valid_lat(lat1), valid_lat(lat2), valid_lon(lon1), valid_lon(lon2))):
        return failure("external.maps.distance", "MAPS_DISTANCE_OUT_OF_RANGE", "coordinates are out of range")
    return lat1, lon1, lat2, lon2
