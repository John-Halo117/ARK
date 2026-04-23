"""Explicit registry for ARK-owned integrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ark.config import IntegrationConfig, load_integration_config
from ark.event_schema import EventSource
from ark.gsb import GSBRecord, GlobalStateBus
from ark.policy_engine import load_policy_set
from ark.runtime_contracts import runtime_contract_registry

from .contracts import IntegrationAdapter, IntegrationHealth, IntegrationRequest, failure
from .docker import DockerStatusAdapter
from .maps import MapsDistanceAdapter, MapsGeocodeAdapter
from .web import WebFetchAdapter, WebSearchAdapter


@dataclass(frozen=True)
class IntegrationRegistry:
    adapters: dict[str, IntegrationAdapter]
    gsb: GlobalStateBus | None = None
    contracts: object | None = None
    policy: object | None = None

    def capabilities(self) -> list[str]:
        return sorted(self.adapters)

    def health(self) -> list[dict[str, object]]:
        return [adapter.health().as_dict() for adapter in self.adapters.values()]

    def execute(self, capability: str, params: dict[str, object]) -> dict[str, object]:
        contracts = self.contracts or runtime_contract_registry()
        policy = self.policy or load_policy_set(Path(__file__).resolve().parents[2] / "policy" / "integration_rules.json")
        decision = policy.evaluate({"capability": capability})
        enabled = decision.output.get("enabled", decision.decision == "allow")
        if not enabled:
            return failure(capability, "INTEGRATION_DISABLED", "local integration disabled by policy").as_dict()
        request_payload = contracts.materialize_payload(
            "runtime.integration.request",
            {"capability": capability, "params": params},
        )
        bus_result = self._publish("integration.request", capability, params)
        if bus_result:
            return bus_result
        adapter = self.adapters.get(capability)
        if adapter is None:
            result = failure(capability, "INTEGRATION_UNKNOWN", "unknown local integration")
            return result.as_dict()
        request = IntegrationRequest(capability=capability, params=request_payload["params"])
        result = contracts.materialize_payload("runtime.integration.result", adapter.execute(request).as_dict())
        bus_result = self._publish("integration.result", capability, _summarize_result(result))
        return bus_result or result

    def _publish(self, action: str, capability: str, payload: dict[str, object]) -> dict[str, object] | None:
        if self.gsb is None:
            return None
        result = self.gsb.publish(
            GSBRecord(
                action=action,
                capability=capability,
                payload=payload,
                source=EventSource.ARK_CORE.value,
                tags={"surface": "integration"},
            )
        )
        return result.as_dict() if result.status == "error" else None


def build_local_registry(
    config: IntegrationConfig | None = None,
    gsb: GlobalStateBus | None = None,
) -> IntegrationRegistry:
    cfg = config or load_integration_config()
    adapters: tuple[IntegrationAdapter, ...] = (
        WebFetchAdapter(cfg),
        WebSearchAdapter(cfg),
        MapsGeocodeAdapter(cfg),
        MapsDistanceAdapter(),
        DockerStatusAdapter(cfg),
    )
    return IntegrationRegistry(
        adapters={adapter.capability: adapter for adapter in adapters},
        gsb=gsb,
        contracts=runtime_contract_registry(),
        policy=load_policy_set(Path(__file__).resolve().parents[2] / "policy" / "integration_rules.json"),
    )


def _summarize_result(result: dict[str, object]) -> dict[str, object]:
    status = str(result.get("status", "ok"))
    summary: dict[str, object] = {"status": status, "keys": sorted(result)[:16]}
    if status == "error":
        summary["error_code"] = str(result.get("error_code", "UNKNOWN"))
    return summary
