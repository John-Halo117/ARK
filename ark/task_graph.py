"""Bounded DAG execution primitives for SD-ARK skills.

What: TaskSpec, linear executor, 10-wide scheduler, chunker, and reducer.
Why: computation is explicit and replayable instead of hidden in agent loops.
Where: called by skills and tests; agents produce specs rather than executing DAGs.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

MAX_CONCURRENCY = 10
MAX_TASK_TIME_SECONDS = 120.0
MAX_TASKS = 128
MAX_DEPENDENCIES = 16
MAX_CHUNKS = 64
MAX_REDUCE_DEPTH = 8

TaskHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(frozen=True)
class TaskSpec:
    id: str
    capability: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    timeout_seconds: float = MAX_TASK_TIME_SECONDS

    def cache_key(self) -> str:
        payload = json.dumps(
            {
                "id": self.id,
                "capability": self.capability,
                "params": self.params,
                "depends_on": self.depends_on,
            },
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        if self.status == "ok":
            return {"status": "ok", "task_id": self.task_id, "output": self.output}
        return {
            "status": "error",
            "task_id": self.task_id,
            "error_code": self.error_code,
            "reason": self.reason,
            "context": {},
            "recoverable": True,
        }


class ReplayCache:
    def __init__(self, max_entries: int = 256):
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: dict[str, TaskResult] = {}
        self._order: list[str] = []

    def get(self, key: str) -> TaskResult | None:
        return self._entries.get(key)

    def put(self, key: str, result: TaskResult) -> None:
        if key not in self._entries:
            self._order.append(key)
        self._entries[key] = result
        if len(self._order) > self._max_entries:
            stale = self._order.pop(0)
            self._entries.pop(stale, None)


class Executor:
    def __init__(self, handlers: Mapping[str, TaskHandler], cache: ReplayCache | None = None):
        self._handlers = dict(handlers)
        self._cache = cache or ReplayCache()

    async def execute(self, task: TaskSpec) -> TaskResult:
        _validate_task(task)
        cached = self._cache.get(task.cache_key())
        if cached is not None:
            return cached
        handler = self._handlers.get(task.capability)
        if handler is None:
            return TaskResult(task.id, "error", error_code="TASK_HANDLER_MISSING", reason="task capability has no handler")
        try:
            result = handler(dict(task.params))
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=min(task.timeout_seconds, MAX_TASK_TIME_SECONDS))
            if not isinstance(result, dict):
                return TaskResult(task.id, "error", error_code="TASK_RESULT_INVALID", reason="task handler must return a dict")
            task_result = TaskResult(task.id, str(result.get("status", "ok")), output=result)
            self._cache.put(task.cache_key(), task_result)
            return task_result
        except asyncio.TimeoutError:
            return TaskResult(task.id, "error", error_code="TASK_TIMEOUT", reason="task exceeded bounded runtime")
        except Exception as exc:
            return TaskResult(task.id, "error", error_code="TASK_EXECUTION_FAILED", reason=str(exc))


class Scheduler:
    def __init__(self, executor: Executor, max_concurrency: int = MAX_CONCURRENCY):
        if max_concurrency <= 0 or max_concurrency > MAX_CONCURRENCY:
            raise ValueError(f"max_concurrency must be in 1..{MAX_CONCURRENCY}")
        self._executor = executor
        self._max_concurrency = max_concurrency

    async def run(self, tasks: Sequence[TaskSpec]) -> list[TaskResult]:
        if len(tasks) > MAX_TASKS:
            raise ValueError(f"task count exceeds bound: {MAX_TASKS}")
        task_map = _task_map(tasks)
        completed: dict[str, TaskResult] = {}
        successful: set[str] = set()
        results: list[TaskResult] = []
        for _pass_index in range(len(task_map)):
            ready = [
                task
                for task in task_map.values()
                if task.id not in completed and all(dep in successful for dep in task.depends_on)
            ]
            if not ready:
                break
            batch = ready[: self._max_concurrency]
            batch_results = await asyncio.gather(*(self._executor.execute(task) for task in batch))
            for result in batch_results[: self._max_concurrency]:
                completed[result.task_id] = result
                if result.status == "ok":
                    successful.add(result.task_id)
                results.append(result)
        if len(completed) != len(task_map):
            missing = sorted(set(task_map) - set(completed))[:MAX_DEPENDENCIES]
            results.append(TaskResult("scheduler", "error", error_code="DAG_UNRESOLVED", reason=f"unresolved tasks: {missing}"))
        return results


def chunk(items: Sequence[Any], chunk_size: int) -> list[list[Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    bounded = list(items[: MAX_CHUNKS * chunk_size])
    chunks: list[list[Any]] = []
    for index in range(0, len(bounded), chunk_size):
        if len(chunks) >= MAX_CHUNKS:
            break
        chunks.append(bounded[index : index + chunk_size])
    return chunks


def reduce_recursive(items: Sequence[Any], reducer: Callable[[Any, Any], Any], *, depth: int = MAX_REDUCE_DEPTH) -> Any:
    if not items:
        return None
    current = list(items[:MAX_CHUNKS])
    for _depth_index in range(depth):
        if len(current) <= 1:
            return current[0]
        next_level: list[Any] = []
        for index in range(0, len(current), 2):
            if index + 1 < len(current):
                next_level.append(reducer(current[index], current[index + 1]))
            else:
                next_level.append(current[index])
        current = next_level
    return current[0]


def _task_map(tasks: Sequence[TaskSpec]) -> dict[str, TaskSpec]:
    mapped: dict[str, TaskSpec] = {}
    for index in range(min(len(tasks), MAX_TASKS)):
        task = tasks[index]
        _validate_task(task)
        if task.id in mapped:
            raise ValueError(f"duplicate task id: {task.id}")
        mapped[task.id] = task
    return mapped


def _validate_task(task: TaskSpec) -> None:
    if not task.id or not task.capability:
        raise ValueError("task id and capability are required")
    if len(task.depends_on) > MAX_DEPENDENCIES:
        raise ValueError(f"task dependencies exceed bound: {MAX_DEPENDENCIES}")
    if task.timeout_seconds <= 0 or task.timeout_seconds > MAX_TASK_TIME_SECONDS:
        raise ValueError(f"task timeout must be in 1..{MAX_TASK_TIME_SECONDS}")
