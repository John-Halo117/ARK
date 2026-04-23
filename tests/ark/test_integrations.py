"""Tests for ARK-owned local integrations."""

from __future__ import annotations

from ark.config import GlobalStateBusConfig, IntegrationConfig
from ark.event_schema import EventSource
from ark.gsb import GlobalStateBus, MemoryGSBSink
from ark.integrations import IntegrationRequest, build_local_registry
from ark.integrations.registry import IntegrationRegistry
from ark.integrations.docker import DockerStatusAdapter
from ark.integrations.maps import MapsDistanceAdapter
from ark.integrations.web import WebSearchAdapter


def test_registry_exposes_local_capabilities():
    registry = build_local_registry(_config())

    assert "external.web.fetch" in registry.capabilities()
    assert "external.web.search" in registry.capabilities()
    assert "external.maps.geocode" in registry.capabilities()
    assert "external.maps.distance" in registry.capabilities()
    assert "system.docker.status" in registry.capabilities()


def test_maps_distance_is_offline_and_bounded():
    adapter = MapsDistanceAdapter()
    result = adapter.execute(
        IntegrationRequest(
            capability="external.maps.distance",
            params={"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1},
        )
    ).as_dict()

    assert result["status"] == "ok"
    assert 100 < result["distance_km"] < 120


def test_maps_distance_rejects_bad_coordinates():
    adapter = MapsDistanceAdapter()
    result = adapter.execute(
        IntegrationRequest(
            capability="external.maps.distance",
            params={"lat1": 91, "lon1": 0, "lat2": 0, "lon2": 1},
        )
    ).as_dict()

    assert result["status"] == "error"
    assert result["error_code"] == "MAPS_DISTANCE_OUT_OF_RANGE"


def test_web_search_requires_local_endpoint():
    adapter = WebSearchAdapter(_config(web_search_url=""))
    result = adapter.execute(
        IntegrationRequest(capability="external.web.search", params={"query": "ark"})
    ).as_dict()

    assert result["status"] == "error"
    assert result["error_code"] == "WEB_SEARCH_UNCONFIGURED"


def test_docker_status_uses_bounded_runner(monkeypatch):
    monkeypatch.setattr("ark.integrations.docker.shutil.which", lambda _cli: "/usr/bin/docker")
    adapter = DockerStatusAdapter(_config(), runner=_docker_runner)

    result = adapter.execute(IntegrationRequest(capability="system.docker.status", params={})).as_dict()

    assert result["status"] == "ok"
    assert result["docker_ready"] is True
    assert result["server_version"] == "25.0"


def test_registry_routes_request_and_result_through_gsb():
    sink = MemoryGSBSink()
    registry = build_local_registry(_config(), gsb=_bus(sink))

    result = registry.execute("external.maps.distance", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1})

    assert result["status"] == "ok"
    assert [event.payload["gsb_action"] for event in sink.events] == [
        "integration.request",
        "integration.result",
    ]


def test_registry_stops_when_gsb_rejects_request():
    adapter = MapsDistanceAdapter()
    sink = MemoryGSBSink()
    registry = IntegrationRegistry({"external.maps.distance": adapter}, _bus(sink))

    result = registry.execute("bad capability", {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 1})

    assert result["status"] == "error"
    assert result["error_code"] == "GSB_RECORD_REJECTED"
    assert sink.events == []


def _config(web_search_url: str = "http://localhost:8080/search") -> IntegrationConfig:
    return IntegrationConfig(
        web_fetch_timeout_s=1,
        web_fetch_max_bytes=4096,
        web_search_url=web_search_url,
        web_search_timeout_s=1,
        web_search_max_results=3,
        maps_geocode_url="",
        maps_timeout_s=1,
        docker_cli="docker",
        docker_timeout_s=1,
    )


def _bus(sink: MemoryGSBSink) -> GlobalStateBus:
    cfg = GlobalStateBusConfig(
        enabled=True,
        max_payload_bytes=4096,
        max_tag_count=8,
        default_source=EventSource.ARK_CORE.value,
    )
    return GlobalStateBus(cfg, (sink,))


def _docker_runner(command, timeout_s):
    assert tuple(command) == ("docker", "info", "--format", "{{json .}}")
    assert timeout_s == 1
    return __import__("subprocess").CompletedProcess(
        args=list(command),
        returncode=0,
        stdout='{"ServerVersion":"25.0","Containers":2,"Images":5}',
        stderr="",
    )
