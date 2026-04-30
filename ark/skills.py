"""Composable SD-ARK skills.

What: named pipelines of TaskSpec objects.
Why: agents call skills/planners, not raw tool inventories.
Where: skill plans feed the DAG scheduler outside the core Step loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ark.task_graph import MAX_TASKS, TaskSpec

MAX_SKILL_STEPS = 32


@dataclass(frozen=True)
class Skill:
    name: str
    steps: tuple[TaskSpec, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("skill name is required")
        if len(self.steps) > MAX_SKILL_STEPS:
            raise ValueError(f"skill step count exceeds bound: {MAX_SKILL_STEPS}")


class SkillRegistry:
    def __init__(self, skills: Sequence[Skill]):
        if len(skills) > MAX_TASKS:
            raise ValueError(f"skill count exceeds bound: {MAX_TASKS}")
        self._skills = {skill.name: skill for skill in skills}

    def plan(self, name: str, inputs: dict[str, Any]) -> tuple[TaskSpec, ...]:
        skill = self._skills.get(name)
        if skill is None:
            raise ValueError(f"unknown skill: {name}")
        planned: list[TaskSpec] = []
        for index in range(min(len(skill.steps), MAX_SKILL_STEPS)):
            step = skill.steps[index]
            params = {**step.params, **inputs}
            planned.append(
                TaskSpec(
                    id=f"{name}.{step.id}",
                    capability=step.capability,
                    params=params,
                    depends_on=tuple(f"{name}.{dep}" for dep in step.depends_on),
                    timeout_seconds=step.timeout_seconds,
                )
            )
        return tuple(planned)


def default_skill_registry() -> SkillRegistry:
    return SkillRegistry(
        (
            Skill(
                "plan_only",
                (
                    TaskSpec("analyze", "code.analyze"),
                    TaskSpec("plan", "reasoning.plan", depends_on=("analyze",)),
                ),
            ),
        )
    )
