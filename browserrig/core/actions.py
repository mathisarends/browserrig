from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _Action:
    id: str
    active: bool = True


class ActionContext:
    """Session-local action correlation, shared by devices and backends."""

    def __init__(self) -> None:
        self._current: ContextVar[_Action | None] = ContextVar(
            "browserrig.action", default=None
        )

    @property
    def action_id(self) -> str:
        action = self._current.get()
        return action.id if action is not None and action.active else ""

    @contextmanager
    def activate(self, action_id: str) -> Generator[None, None, None]:
        action = _Action(action_id)
        token = self._current.set(action)
        try:
            yield
        finally:
            action.active = False
            self._current.reset(token)
