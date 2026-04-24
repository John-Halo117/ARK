"""Central bounded math helpers for Forge runtime code."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088
KM_TO_MILES = 0.621371


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    start_lat = radians(lat1)
    end_lat = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(start_lat) * cos(end_lat) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def valid_lat(value: float) -> bool:
    return -90.0 <= value <= 90.0


def valid_lon(value: float) -> bool:
    return -180.0 <= value <= 180.0
