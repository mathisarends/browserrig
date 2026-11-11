from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from harnessed import ToolError, ToolResult

from browserrig.browser import Tab
from browserrig.core import ActionKind


@dataclass
class ToolAction:
    kind: ActionKind
    tab: Tab | None = None
    action_id: str = ""
    started: bool = False
    dispatch_tracked: bool = False
    dispatched: bool = False
    preparation_notes: list[str] = field(default_factory=list)
    preparation_omitted: int = 0
    active: bool = True
    result: ToolResult | None = None


class ToolActionError(ToolError):
    def __init__(self, result: ToolResult) -> None:
        super().__init__(result.text)
        self.result = result


class ActionContext:
    """Bind one addressed action to its task and invalidate inherited copies on exit."""

    def __init__(self) -> None:
        self._current: ContextVar[ToolAction | None] = ContextVar(
            "browserrig.tool_action", default=None
        )

    @property
    def current(self) -> ToolAction | None:
        action = self._current.get()
        return action if action is not None and action.active else None

    @property
    def tab(self) -> Tab:
        action = self.current
        if action is None or action.tab is None:
            raise RuntimeError("An implicit tab requires an executing action tool")
        return action.tab

    @contextmanager
    def activate(
        self, kind: ActionKind, *, dispatch_tracked: bool = False
    ) -> Generator[ToolAction, None, None]:
        action = ToolAction(kind, dispatch_tracked=dispatch_tracked)
        token = self._current.set(action)
        try:
            yield action
        finally:
            action.active = False
            self._current.reset(token)
