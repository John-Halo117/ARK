"""Central UTC time helpers for ARK Python services."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def utc_now_naive() -> datetime:
    return utc_now().replace(tzinfo=None)


def utc_timestamp() -> int:
    return int(utc_now().timestamp())
