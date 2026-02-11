from __future__ import annotations

from typing import Any, Callable, Dict

TaskFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
_REGISTRY: dict[str, TaskFn] = {}


def task(task_type: str):
    def _decorator(fn: TaskFn) -> TaskFn:
        _REGISTRY[task_type] = fn
        return fn
    return _decorator


def get(task_type: str) -> TaskFn:
    if task_type not in _REGISTRY:
        raise KeyError(f"Unknown task_type: {task_type}")
    return _REGISTRY[task_type]


def list_task_types() -> list[str]:
    return sorted(_REGISTRY.keys())
