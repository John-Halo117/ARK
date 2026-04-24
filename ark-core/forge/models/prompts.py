"""Prompt builders for optional Ollama-backed Forge components."""

from __future__ import annotations

import json

from ..types import ContextBundle


def build_diff_prompt(context: ContextBundle) -> str:
    """Request a bounded unified diff only."""

    files = "\n".join(f"- {path}" for path in context.excerpts) or "- none"
    excerpts = "\n\n".join(
        f"FILE {path}\n{body}" for path, body in context.excerpts.items()
    )
    constraints = list(context.task.constraints)
    constraints.extend(
        str(item) for item in list((context.plan or {}).get("constraints", []))
    )
    rendered_constraints = (
        "\n".join(f"- {item}" for item in constraints)
        or "- preserve behavior unless tests demand change"
    )
    plan = json.dumps(context.plan or {}, indent=2, sort_keys=True)
    return f"""Forge executor task
Identity:
- local deterministic coding engine
- diff-only output
- no prose
- bounded patch touching only the files that matter

Summary: {context.task.summary}
Scope: {context.task.scope}
Todo: {context.task.todo}
Known hot regions: {list(context.ban_hotspots)}
Target files:
{files}
Constraints:
{rendered_constraints}
Plan:
{plan}

Repository excerpts:
{excerpts}

Return ONLY a unified diff.
- start with "diff --git" whenever possible
- do not include explanations
- do not use markdown fences
- do not invent files outside the target/problem area unless necessary for tests
"""


def build_plan_prompt(context: ContextBundle) -> str:
    """Ask the planner for bounded structured guidance."""

    files = "\n".join(f"- {path}" for path in context.excerpts) or "- none"
    return f"""Build a bounded JSON plan for this coding task.
Summary: {context.task.summary}
Scope: {context.task.scope}
Todo: {context.task.todo}
Known hot regions: {list(context.ban_hotspots)}
Current candidate files:
{files}

Return JSON with keys:
- target_files
- strategies
- risk_map
- constraints
"""


def build_attack_prompt(context: ContextBundle, delta: str, mode: str) -> str:
    """Ask for a structured adversarial critique."""

    return f"""You are Forge redteam mode={mode}.
Task: {context.task.summary}
Focus:
- logic breaks
- edge cases
- regressions
- exploitability
- minimal repros
Diff:
{delta}

Return JSON with keys:
- risk
- findings
- attacker
- repro_inputs
- counterfactuals
"""
