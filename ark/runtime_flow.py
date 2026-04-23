"""Shared audited runtime flow helpers for GSB-backed services."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ark.event_schema import EventType
from ark.gsb import GSBRecord, GlobalStateBus
from ark.runtime_contracts import ContractValidationError, RuntimeContractRegistry, runtime_contract_registry

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(frozen=True)
class DispatchDescriptor:
    capability: str
    handler: Handler
    request_contract: str | None = None
    response_contract: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


class DispatchRegistry:
    def __init__(
        self,
        descriptors: tuple[DispatchDescriptor, ...],
        contracts: RuntimeContractRegistry | None = None,
    ):
        self._descriptors = {descriptor.capability: descriptor for descriptor in descriptors}
        self.contracts = contracts or runtime_contract_registry()

    def resolve(self, capability: str) -> DispatchDescriptor | None:
        return self._descriptors.get(capability)

    def capabilities(self) -> list[str]:
        return sorted(self._descriptors)


class RuntimeAudit:
    def __init__(
        self,
        gsb: GlobalStateBus,
        *,
        source: str,
        surface: str,
        default_tags: dict[str, str] | None = None,
    ):
        self._gsb = gsb
        self._source = source
        self._surface = surface
        self._default_tags = default_tags or {}

    def record(
        self,
        action: str,
        capability: str,
        payload: dict[str, Any],
        *,
        event_type: str = EventType.STATUS.value,
        tags: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        action_name = action if action.startswith(f"{self._surface}.") else f"{self._surface}.{action}"
        result = self._gsb.publish(
            GSBRecord(
                action=action_name,
                capability=capability,
                payload=payload,
                source=self._source,
                event_type=event_type,
                tags={**self._default_tags, **(tags or {})},
            )
        )
        if result.status == "ok":
            return None
        return runtime_failure(
            result.error_code or "GSB_RECORD_REJECTED",
            result.reason or "gsb rejected runtime feed",
            result.context,
            recoverable=result.recoverable,
            capability=capability,
        )

    async def publish_json(
        self,
        target: Any,
        subject: str,
        payload: dict[str, Any],
        capability: str,
        *,
        action: str = "publish",
        tags: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        error = self.record(
            action,
            capability,
            {"subject": subject, "keys": sorted(payload)[:16]},
            tags=tags,
        )
        if error:
            return error
        await target.publish(subject, json.dumps(payload).encode())
        return None

    async def execute(self, registry: DispatchRegistry, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        descriptor = registry.resolve(capability)
        if descriptor is None:
            failure = runtime_failure(
                "CAPABILITY_UNKNOWN",
                f"Unknown capability: {capability}",
                {"capability": capability},
                capability=capability,
            )
            self.record(
                "capability.failure",
                capability,
                {"error_code": failure["error_code"], "reason": failure["reason"]},
                event_type=EventType.ERROR.value,
            )
            return failure

        try:
            request = params
            if descriptor.request_contract:
                request = registry.contracts.materialize_payload(descriptor.request_contract, params)
            error = self.record(
                "capability.request",
                capability,
                {"params": _bounded_value(request)},
                tags=descriptor.tags,
            )
            if error:
                return error
            result = descriptor.handler(request)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise TypeError(f"handler for {capability} must return a dict")
            if descriptor.response_contract:
                result = registry.contracts.materialize_payload(descriptor.response_contract, result)
            error = self.record(
                "capability.result",
                capability,
                summarize_result(result),
                tags=descriptor.tags,
            )
            return error or result
        except ContractValidationError as exc:
            failure = runtime_failure(
                exc.failure.error_code,
                exc.failure.reason,
                exc.failure.context,
                recoverable=exc.failure.recoverable,
                capability=capability,
            )
        except Exception as exc:
            failure = runtime_failure(
                "RUNTIME_EXECUTION_FAILED",
                str(exc),
                {"capability": capability},
                capability=capability,
            )
        self.record(
            "capability.failure",
            capability,
            {"error_code": failure["error_code"], "reason": failure["reason"]},
            event_type=EventType.ERROR.value,
            tags=descriptor.tags,
        )
        return failure


def runtime_failure(
    error_code: str,
    reason: str,
    context: dict[str, Any] | None = None,
    *,
    recoverable: bool = True,
    capability: str = "",
) -> dict[str, Any]:
    failure = {
        "status": "error",
        "error_code": error_code,
        "reason": reason,
        "context": context or {},
        "recoverable": recoverable,
        "error": reason,
    }
    if capability:
        failure["capability"] = capability
    return failure


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"status": result.get("status", "ok"), "keys": sorted(result)[:16]}
    if "error_code" in result:
        summary["error_code"] = result["error_code"]
    return summary


def _bounded_value(value: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(value, default=str)
    if len(raw.encode("utf-8")) <= 8192:
        return value
    return {"truncated": True, "bytes": len(raw.encode("utf-8"))}
