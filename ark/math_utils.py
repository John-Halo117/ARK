"""Central bounded math helpers for ARK Python services."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from statistics import mean, stdev
from typing import Sequence

EARTH_RADIUS_KM = 6371.0088


def safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def valid_lat(value: float) -> bool:
    return -90.0 <= value <= 90.0


def valid_lon(value: float) -> bool:
    return -180.0 <= value <= 180.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    start_lat = radians(lat1)
    end_lat = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(start_lat) * cos(end_lat) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def zscore_anomaly(
    samples: Sequence[float],
    value: float,
    *,
    threshold: float = 3.0,
    min_samples: int = 5,
    max_samples: int = 100,
) -> bool:
    bounded = [float(sample) for sample in samples[-max_samples:]]
    if len(bounded) < min_samples:
        return False
    sigma = stdev(bounded) if len(bounded) > 1 else 1.0
    return abs(value - mean(bounded)) / (sigma or 1.0) > threshold
