from dataclasses import replace

from harnessed import ToolError, ToolResult
from harnessed.hooks import Next

from browserrig.browser import Tab
from browserrig.core import ActionKind, BrowserCoordination, BrowserToolCall
from browserrig.tools.effects import Effect

from .context import InvocationContext, ToolActionError
from .policy import ACTION_KINDS, EXPECTED_CHANGES, NAVIGATION_KINDS, TAB_KINDS
from .transaction import ActionRunner


class ToolExecution:
    """Adapt raw tool returns to an action while preserving passive and rich results."""

    def __init__(self, runner: ActionRunner, coordination: BrowserCoordination) -> None:
        self._runner = runner
        self._coordination = coordination
        self.context = InvocationContext()

    async def run(self, event: BrowserToolCall, next_: Next[object]) -> object:
        kind = event.metadata.kind
        if kind not in ACTION_KINDS:
            if kind == ActionKind.WAIT:
                async with self._coordination.exclusive():
                    return await next_()
            return await next_()

        with self.context.activate(kind) as action:

            async def perform(_tab: Tab) -> Effect:
                value = await next_()
                if isinstance(value, Effect):
                    return value
                if isinstance(value, ToolResult):
                    if value.is_error:
                        raise ToolActionError(value)
                    action.result = value
                    return Effect(value.text, break_chain=value.break_chain)
                if isinstance(value, str):
                    return Effect(value)
                raise ToolError(
                    "Page input tools must return Effect, ToolResult or text"
                )

            settle = kind not in TAB_KINDS and not (
                kind in NAVIGATION_KINDS and event.arguments.get("new_tab", False)
            )
            result = await self._runner.run(
                kind=kind,
                operation=perform,
                settle=settle,
                expects_change=kind in EXPECTED_CHANGES,
                action=action,
            )
            original = action.result
            if original is None:
                return result
            return replace(
                original
                if original.text == result.text
                else original.with_text(result.text),
                break_chain=original.break_chain or result.break_chain,
            )
