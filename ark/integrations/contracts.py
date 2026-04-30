"""Strict contracts for ARK local integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class IntegrationRequest:
    capability: str
    params: dict[str, Any]


@dataclass(frozen=True)
class IntegrationHealth:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class IntegrationResult:
    status: str
    capability: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        if self.status == "error":
            return {
                "status": "error",
                "capability": self.capability,
                "error_code": self.error_code,
                "reason": self.reason,
                "context": self.context,
                "recoverable": self.recoverable,
            }
        return {"status": "ok", "capability": self.capability, **self.data}


class IntegrationAdapter(Protocol):
    capability: str

    def health(self) -> IntegrationHealth: ...

    def execute(self, request: IntegrationRequest) -> IntegrationResult: ...


def success(capability: str, data: dict[str, Any]) -> IntegrationResult:
    return IntegrationResult(status="ok", capability=capability, data=data, recoverable=False)


def failure(
    capability: str,
    error_code: str,
    reason: str,
    *,
    context: dict[str, Any] | None = None,
    recoverable: bool = True,
) -> IntegrationResult:
    return IntegrationResult(
        status="error",
        capability=capability,
        error_code=error_code,
        reason=reason,
        context=context or {},
        recoverable=recoverable,
    )
