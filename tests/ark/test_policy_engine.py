"""Tests for runtime policy evaluation."""

from pathlib import Path

from ark.policy_engine import load_policy_set


ROOT = Path(__file__).resolve().parents[2]


def test_autoscaler_policy_scales_up_on_queue():
    policy = load_policy_set(ROOT / "policy" / "autoscaler_rules.json")
    decision = policy.evaluate(
        {
            "demand": 100,
            "latency": 0,
            "instance_count": 1,
            "queue_threshold": 10,
            "latency_threshold": 1000,
            "min_instances": 1,
            "max_instances": 5,
        }
    )
    assert decision.decision == "scale_up"
    assert decision.rule_name == "scale_up_on_queue_depth"


def test_autoscaler_policy_scales_down_when_idle():
    policy = load_policy_set(ROOT / "policy" / "autoscaler_rules.json")
    decision = policy.evaluate(
        {
            "demand": 0,
            "latency": 0,
            "instance_count": 3,
            "queue_threshold": 10,
            "latency_threshold": 1000,
            "min_instances": 1,
            "max_instances": 5,
        }
    )
    assert decision.decision == "scale_down"


def test_emitter_policy_routes_climate_entities():
    policy = load_policy_set(ROOT / "policy" / "emitter_rules.json")
    decision = policy.evaluate({"entity_prefix": "climate"})
    assert decision.output["subject"] == "ark.event.climate.temperature"
    assert decision.output["value_mode"] == "attribute"
