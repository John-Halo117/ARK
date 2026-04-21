#!/usr/bin/env python3
"""Enforce ARK scope/todo/priority policy for automated batches."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TierRules:
    scope_tiers: dict[str, int]
    todo_tiers: dict[str, int]
    manual_review_from: int
    blocked_auto_promote_scopes: set[str]
    forbid_mixed_todo_batches: bool
    reject_mixed_scope_escalation: bool


@dataclass(frozen=True)
class WorkItem:
    identifier: str
    scope: str
    todo: str


def load_rules(path: Path) -> TierRules:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "scope_tiers",
        "todo_tiers",
        "manual_review_from",
        "blocked_auto_promote_scopes",
        "forbid_mixed_todo_batches",
        "reject_mixed_scope_escalation",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"rules file missing keys: {', '.join(missing)}")

    return TierRules(
        scope_tiers={key: int(value) for key, value in payload["scope_tiers"].items()},
        todo_tiers={key: int(value) for key, value in payload["todo_tiers"].items()},
        manual_review_from=int(payload["manual_review_from"]),
        blocked_auto_promote_scopes=set(payload["blocked_auto_promote_scopes"]),
        forbid_mixed_todo_batches=bool(payload["forbid_mixed_todo_batches"]),
        reject_mixed_scope_escalation=bool(payload["reject_mixed_scope_escalation"]),
    )


def validate_rules(rules: TierRules) -> None:
    if not rules.scope_tiers or not rules.todo_tiers:
        raise ValueError("scope and todo tiers must not be empty")
    if rules.manual_review_from < 1:
        raise ValueError("manual_review_from must be at least 1")
    for label, score in {**rules.scope_tiers, **rules.todo_tiers}.items():
        if score < 1:
            raise ValueError(f"tier {label} must map to a positive integer")


def load_batch(path: Path) -> list[WorkItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload["items"] if isinstance(payload, dict) else payload
    return [
        WorkItem(
            identifier=item.get("id", f"item-{idx + 1}"),
            scope=item["scope"],
            todo=item["todo"],
        )
        for idx, item in enumerate(raw_items)
    ]


def priority_for(item: WorkItem, rules: TierRules) -> int:
    if item.scope not in rules.scope_tiers:
        raise ValueError(f"unknown scope tier: {item.scope}")
    if item.todo not in rules.todo_tiers:
        raise ValueError(f"unknown todo tier: {item.todo}")
    return max(rules.scope_tiers[item.scope], rules.todo_tiers[item.todo])


def priority_label(priority: int) -> str:
    return f"P{priority}"


def evaluate_batch(
    items: list[WorkItem],
    rules: TierRules,
) -> tuple[list[dict[str, str]], list[str]]:
    summary: list[dict[str, str]] = []
    violations: list[str] = []
    todo_values = {item.todo for item in items}
    scope_values = {item.scope for item in items}

    if rules.forbid_mixed_todo_batches and len(todo_values) > 1:
        violations.append("mixed todo tiers are not allowed in one batch")
    if rules.reject_mixed_scope_escalation and len(scope_values) > 1:
        violations.append("mixed scope escalation is not allowed in one batch")

    for item in items:
        priority = priority_for(item, rules)
        summary.append(
            {
                "id": item.identifier,
                "scope": item.scope,
                "todo": item.todo,
                "priority": priority_label(priority),
            }
        )
        if item.scope in rules.blocked_auto_promote_scopes:
            violations.append(f"{item.identifier}: scope {item.scope} cannot auto-promote")
        if priority >= rules.manual_review_from:
            violations.append(
                f"{item.identifier}: {priority_label(priority)} requires manual approval"
            )

    return summary, violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules",
        type=Path,
        required=True,
        help="Path to tiering_rules.json",
    )
    parser.add_argument("--batch", type=Path, help="JSON file containing work items")
    parser.add_argument(
        "--validate-rules-only",
        action="store_true",
        help="Validate the rule file without evaluating a batch",
    )
    args = parser.parse_args()

    try:
        rules = load_rules(args.rules)
        validate_rules(rules)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.validate_rules_only or args.batch is None:
        print(json.dumps({"status": "ok", "rules": str(args.rules)}, indent=2))
        return 0

    try:
        items = load_batch(args.batch)
        summary, violations = evaluate_batch(items, rules)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps({"items": summary, "violations": violations}, indent=2))
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
