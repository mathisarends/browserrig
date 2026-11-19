from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from harnessed import ToolError, ToolResult

from browserrig.browser import Tab
from browserrig.core import ActionKind

LABEL_CHARS = 80


@dataclass
class ToolAction:
    kind: ActionKind
    tab: Tab | None = None
    action_id: str = ""
    call_id: str = ""
    label: str = ""
    tool_name: str = ""
    started: bool = False
    preparation_notes: list[str] = field(default_factory=list)
    preparation_omitted: int = 0
    active: bool = True
    result: ToolResult | None = None


@dataclass(frozen=True, slots=True)
class CallIdentity:
    """The originating tool call of an action, safe to publish in lifecycle events."""

    call_id: str = ""
    label: str = ""
    tool_name: str = ""


NO_CALL = CallIdentity()


class ToolActionError(ToolError):
    def __init__(self, result: ToolResult) -> None:
        super().__init__(result.text)
        self.result = result


class InvocationContext:
    """Bind one addressed action to its task and invalidate inherited copies on exit."""

    def __init__(self) -> None:
        self._current: ContextVar[ToolAction | None] = ContextVar(
            "browserrig.tool_action", default=None
        )
        self._call: ContextVar[CallIdentity] = ContextVar(
            "browserrig.tool_call", default=NO_CALL
        )

    @property
    def call(self) -> CallIdentity:
        """The tool call executing in this task, or an empty identity outside one."""
        return self._call.get()

    @contextmanager
    def bind_call(
        self, call_id: str, label: str, tool_name: str
    ) -> Generator[None, None, None]:
        token = self._call.set(CallIdentity(call_id, label[:LABEL_CHARS], tool_name))
        try:
            yield
        finally:
            self._call.reset(token)

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
        self, kind: ActionKind, tool_name: str
    ) -> Generator[ToolAction, None, None]:
        call = self.call
        action = ToolAction(
            kind,
            call_id=call.call_id,
            label=call.label,
            tool_name=call.tool_name or tool_name,
        )
        token = self._current.set(action)
        try:
            yield action
        finally:
            action.active = False
            self._current.reset(token)
