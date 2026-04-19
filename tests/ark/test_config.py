"""Tests for centralized runtime configuration loading."""

from __future__ import annotations

from ark import config


def test_service_runtime_defaults(monkeypatch):
    monkeypatch.delenv("INSTANCE_ID", raising=False)
    monkeypatch.delenv("NATS_URL", raising=False)

    runtime = config.load_service_runtime_config()

    assert runtime.nats_url == "nats://nats:4222"
    assert len(runtime.instance_id) == 12


def test_service_runtime_rejects_bad_instance_id(monkeypatch):
    monkeypatch.setenv("INSTANCE_ID", "bad id with spaces")
    runtime = config.load_service_runtime_config()
    assert runtime.instance_id != "bad id with spaces"


def test_gateway_url_validation(monkeypatch):
    monkeypatch.setenv("NATS_URL", "file:///etc/passwd")
    monkeypatch.setenv("MESH_URL", "gopher://mesh")

    gateway = config.load_gateway_config()

    assert gateway.nats_url == "nats://nats:4222"
    assert gateway.mesh_url == "http://ark-mesh:7000"


def test_unifi_enforces_https_default(monkeypatch):
    monkeypatch.setenv("UNIFI_URL", "http://unifi:8443")
    cfg = config.load_unifi_config()
    assert cfg.unifi_url == "https://unifi:8443"
