"""Bounded HTTP helpers for ARK-owned integrations."""

from __future__ import annotations

import json
from urllib import request
from urllib.parse import urlencode, urlparse, urlunparse


def fetch_text(url: str, *, timeout_s: int, max_bytes: int) -> tuple[int, str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be http(s)")
    req = request.Request(url, headers={"User-Agent": "ARK-local-integrations/1.0"})
    with request.urlopen(req, timeout=timeout_s) as response:
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("response exceeds byte budget")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return int(response.status), response.headers.get_content_type(), text


def fetch_json(url: str, *, timeout_s: int, max_bytes: int) -> object:
    _status, _content_type, text = fetch_text(url, timeout_s=timeout_s, max_bytes=max_bytes)
    return json.loads(text)


def append_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    separator = "&" if parsed.query else ""
    query = f"{parsed.query}{separator}{urlencode(params)}"
    return urlunparse(parsed._replace(query=query))
