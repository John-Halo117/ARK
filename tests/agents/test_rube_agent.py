"""Tests for agents.rube.agent module."""

import pytest

from agents.rube.agent import Agent


class TestRubeAgent:
    def setup_method(self):
        self.agent = Agent()

    # ---- init & subscriptions ----

    def test_init_name(self):
        assert self.agent.name == "Rube"

    def test_version(self):
        assert Agent.__version__ == "1.0.0"

    def test_subscriptions(self):
        assert self.agent.get_event_subscriptions() == [
            "graph.query",
            "entity.relate",
            "relationship.infer",
        ]

    # ---- handle_event dispatching ----

    def test_handle_graph_query(self):
        event = {"type": "graph.query", "payload": {"query": "find X", "entity_type": "device"}}
        result = self.agent.handle_event(event)

        assert result["agent"] == "Rube"
        assert result["action"] == "query"
        assert result["query"] == "find X"
        assert isinstance(result["entities"], list)
        assert isinstance(result["edges"], list)

    def test_handle_entity_relate(self):
        event = {
            "type": "entity.relate",
            "payload": {
                "entity_a": "sensor.temp",
                "entity_b": "climate.hvac",
                "relation_type": "controls",
            },
        }
        result = self.agent.handle_event(event)

        assert result["agent"] == "Rube"
        assert result["action"] == "relate"
        assert result["from"] == "sensor.temp"
        assert result["to"] == "climate.hvac"
        assert result["relation"] == "controls"
        assert result["created"] is True

    def test_handle_relationship_infer(self):
        event = {
            "type": "relationship.infer",
            "payload": {
                "entities": ["a", "b", "c"],
                "context": {"domain": "iot"},
            },
        }
        result = self.agent.handle_event(event)

        assert result["agent"] == "Rube"
        assert result["action"] == "infer"
        assert result["input_entities"] == 3
        assert isinstance(result["inferred_relations"], list)
        assert isinstance(result["confidence_scores"], dict)

    def test_handle_event_unknown_type(self):
        event = {"type": "unknown.event", "payload": {}}
        result = self.agent.handle_event(event)
        assert result is None

    # ---- individual capability methods ----

    def test_query_graph_defaults(self):
        result = self.agent.query_graph({})
        assert result["query"] == ""
        assert result["entities"] == []
        assert result["edges"] == []

    def test_relate_entities_default_relation(self):
        result = self.agent.relate_entities({"entity_a": "a", "entity_b": "b"})
        assert result["relation"] == "related_to"

    def test_infer_relationships_empty(self):
        result = self.agent.infer_relationships({})
        assert result["input_entities"] == 0
