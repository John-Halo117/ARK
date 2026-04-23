"""Local-first web integration adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ark.config import IntegrationConfig
from ark.security import sanitize_string

from .contracts import IntegrationHealth, IntegrationRequest, IntegrationResult, failure, success
from .http import append_query, fetch_json, fetch_text


@dataclass(frozen=True)
class WebFetchAdapter:
    config: IntegrationConfig
    capability: str = "external.web.fetch"

    def health(self) -> IntegrationHealth:
        return IntegrationHealth(self.capability, True, "bounded http(s) fetch ready")

    def execute(self, request: IntegrationRequest) -> IntegrationResult:
        url = sanitize_string(str(request.params.get("url", "")), 2048)
        if not url:
            return failure(self.capability, "WEB_FETCH_MISSING_URL", "url is required")
        try:
            status, content_type, text = fetch_text(
                url,
                timeout_s=self.config.web_fetch_timeout_s,
                max_bytes=self.config.web_fetch_max_bytes,
            )
        except (OSError, ValueError) as exc:
            return failure(self.capability, "WEB_FETCH_FAILED", str(exc), context={"url": url})
        return success(
            self.capability,
            {
                "url": url,
                "http_status": status,
                "content_type": content_type,
                "text": sanitize_string(text, self.config.web_fetch_max_bytes),
                "truncated": False,
            },
        )


@dataclass(frozen=True)
class WebSearchAdapter:
    config: IntegrationConfig
    capability: str = "external.web.search"

    def health(self) -> IntegrationHealth:
        ok = bool(self.config.web_search_url)
        detail = "local search endpoint configured" if ok else "set ARK_WEB_SEARCH_URL"
        return IntegrationHealth(self.capability, ok, detail)

    def execute(self, request: IntegrationRequest) -> IntegrationResult:
        if not self.config.web_search_url:
            return failure(self.capability, "WEB_SEARCH_UNCONFIGURED", "set ARK_WEB_SEARCH_URL")
        query = sanitize_string(str(request.params.get("query", "")), 512)
        if not query:
            return failure(self.capability, "WEB_SEARCH_MISSING_QUERY", "query is required")
        try:
            payload = fetch_json(
                _search_url(self.config.web_search_url, query),
                timeout_s=self.config.web_search_timeout_s,
                max_bytes=self.config.web_fetch_max_bytes,
            )
        except (OSError, ValueError) as exc:
            return failure(self.capability, "WEB_SEARCH_FAILED", str(exc), context={"query": query})
        return success(
            self.capability,
            {"query": query, "results": _normalize_results(payload, self.config.web_search_max_results)},
        )


def _search_url(base_url: str, query: str) -> str:
    if "{query}" in base_url:
        return base_url.replace("{query}", query)
    return append_query(base_url, {"q": query})


def _normalize_results(payload: object, limit: int) -> list[dict[str, Any]]:
    rows = _result_rows(payload)
    return [_normalize_result(row) for row in rows[:limit]]


def _result_rows(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("results", "hits", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalize_result(row: object) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"title": sanitize_string(str(row), 256), "url": "", "snippet": ""}
    return {
        "title": sanitize_string(str(row.get("title", row.get("name", ""))), 256),
        "url": sanitize_string(str(row.get("url", row.get("link", ""))), 2048),
        "snippet": sanitize_string(str(row.get("snippet", row.get("content", ""))), 1024),
    }
