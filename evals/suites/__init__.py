"""Benchmark missions on live websites, grouped into stages by how stable the pages are.

Expected values of the practice and reference stages were checked against the live sites
on 2026-11-08. When a check fails for every model, look at the site before the agent.
"""

from ..task import Task
from .practice import PRACTICE
from .reference import REFERENCE
from .wild import WILD

TASKS: tuple[Task, ...] = (*PRACTICE, *REFERENCE, *WILD)


def select(spec: str | None) -> list[Task]:
    """Comma-separated task names, `@stage` or `@tag`; empty selects every task."""
    if not spec:
        return list(TASKS)
    by_name = {task.name: task for task in TASKS}
    chosen: dict[str, Task] = {}
    for item in (part.strip() for part in spec.split(",") if part.strip()):
        if item.startswith("@"):
            key = item[1:]
            matches = [t for t in TASKS if key in (t.stage, *t.tags)]
            if not matches:
                raise SystemExit(f"No task has stage or tag {key!r}")
        elif item in by_name:
            matches = [by_name[item]]
        else:
            raise SystemExit(f"Unknown task {item!r}")
        chosen.update((task.name, task) for task in matches)
    return list(chosen.values())


__all__ = ["TASKS", "Task", "select"]
