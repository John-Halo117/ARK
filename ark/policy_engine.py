"""Minimal policy-as-code evaluator for ARK runtime surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ark.security import sanitize_string

_MAX_POLICY_BYTES = 131_072


@dataclass(frozen=True)
class PolicyCondition:
    field: str
    op: str
    value: Any = None
    ref: str = ""


@dataclass(frozen=True)
class PolicyRule:
    name: str
    decision: str
    conditions: tuple[PolicyCondition, ...] = ()
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    rule_name: str
    policy_name: str
    policy_version: str
    output: dict[str, Any]
    context: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "rule_name": self.rule_name,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "output": self.output,
            "context": self.context,
        }


@dataclass(frozen=True)
class PolicySet:
    name: str
    version: str
    rules: tuple[PolicyRule, ...]
    default_decision: str
    extras: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, context: dict[str, Any]) -> PolicyDecision:
        for rule in self.rules:
            if _matches_rule(rule, context):
                return PolicyDecision(
                    decision=rule.decision,
                    rule_name=rule.name,
                    policy_name=self.name,
                    policy_version=self.version,
                    output=dict(rule.output),
                    context=_bounded_context(context),
                )
        return PolicyDecision(
            decision=self.default_decision,
            rule_name="default",
            policy_name=self.name,
            policy_version=self.version,
            output={},
            context=_bounded_context(context),
        )

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": True,
            "version": self.version,
            "rules": len(self.rules),
        }


def load_policy_set(path: str | Path) -> PolicySet:
    policy_path = Path(path)
    raw = policy_path.read_text(encoding="utf-8")
    encoded = raw.encode("utf-8")
    if len(encoded) > _MAX_POLICY_BYTES:
        raise ValueError(f"policy file too large: {policy_path}")
    document = json.loads(raw)
    version = sanitize_string(str(document.get("version", "v1")), 32)
    rules_doc = document.get("rules", [])
    if not isinstance(rules_doc, list):
        raise ValueError(f"policy rules must be a list: {policy_path}")
    rules = tuple(_parse_rule(rule_doc) for rule_doc in rules_doc)
    extras = {
        key: value
        for key, value in document.items()
        if key not in {"version", "rules", "default_decision"}
    }
    return PolicySet(
        name=policy_path.stem,
        version=version,
        rules=rules,
        default_decision=sanitize_string(str(document.get("default_decision", "no_match")), 64),
        extras=extras,
    )


def _parse_rule(rule_doc: Any) -> PolicyRule:
    if not isinstance(rule_doc, dict):
        raise ValueError("policy rule must be an object")
    name = sanitize_string(str(rule_doc.get("name", "")), 128)
    decision = sanitize_string(str(rule_doc.get("decision", "")), 128)
    conditions_doc = rule_doc.get("conditions", [])
    if not isinstance(conditions_doc, list):
        raise ValueError(f"policy rule conditions must be a list: {name}")
    conditions = tuple(
        PolicyCondition(
            field=sanitize_string(str(condition.get("field", "")), 128),
            op=sanitize_string(str(condition.get("op", "")), 32),
            value=condition.get("value"),
            ref=sanitize_string(str(condition.get("ref", "")), 128),
        )
        for condition in conditions_doc
        if isinstance(condition, dict)
    )
    output = rule_doc.get("output", {})
    if not isinstance(output, dict):
        raise ValueError(f"policy rule output must be an object: {name}")
    return PolicyRule(name=name, decision=decision, conditions=conditions, output=output)


def _matches_rule(rule: PolicyRule, context: dict[str, Any]) -> bool:
    return all(_matches_condition(condition, context) for condition in rule.conditions)


def _matches_condition(condition: PolicyCondition, context: dict[str, Any]) -> bool:
    left = context.get(condition.field)
    right = context.get(condition.ref) if condition.ref else condition.value
    if condition.op == "eq":
        return left == right
    if condition.op == "ne":
        return left != right
    if condition.op == "gt":
        return _compare_numbers(left, right, lambda lhs, rhs: lhs > rhs)
    if condition.op == "gte":
        return _compare_numbers(left, right, lambda lhs, rhs: lhs >= rhs)
    if condition.op == "lt":
        return _compare_numbers(left, right, lambda lhs, rhs: lhs < rhs)
    if condition.op == "lte":
        return _compare_numbers(left, right, lambda lhs, rhs: lhs <= rhs)
    if condition.op == "prefix":
        return isinstance(left, str) and isinstance(right, str) and left.startswith(right)
    if condition.op == "in":
        return left in right if isinstance(right, (list, tuple, set)) else False
    return False


def _compare_numbers(left: Any, right: Any, comparator) -> bool:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return comparator(left, right)


def _bounded_context(context: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(context, default=str)
    if len(raw.encode("utf-8")) <= 8192:
        return context
    return {"truncated": True, "bytes": len(raw.encode("utf-8"))}
