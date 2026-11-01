from harnessed import Inject, Plugin, ToolResult
from harnessed.kernel import dependency

from browserrig.browser import Tab
from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.observation import Observe

from .execution import Actions, Effect


class FormTools(Plugin, needs=(Actions,)):
    _observe = dependency(Observe)

    @tool(
        kind=ActionKind.SELECT,
        chainable=True,
        description="Select an exact option label or value in a native select element.",
    )
    async def select_option(
        self,
        ref: str,
        value: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def check(tab: Tab) -> None:
            await self._observe.dom_element(tab, ref)

        async def select(tab: Tab) -> Effect:
            await actions.element_point(tab=tab, ref=ref)
            handle = await self._observe.dom_element(tab, ref)
            await handle.select(value)
            return Effect("Option selected.")

        return await actions.run(
            kind=ActionKind.SELECT,
            operation=select,
            check=check,
        )

    @tool(
        kind=ActionKind.SET_DATE,
        chainable=True,
        description="Set a native date/time input in its HTML format, such as YYYY-MM-DD.",
    )
    async def set_date(
        self,
        ref: str,
        value: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def check(tab: Tab) -> None:
            handle = await self._observe.dom_element(tab, ref)
            if handle.element.input_type not in {
                "date",
                "time",
                "datetime-local",
                "month",
                "week",
            }:
                raise BrowserError("Element is not a native date/time input")

        async def set_date(tab: Tab) -> Effect:
            await actions.element_point(tab=tab, ref=ref)
            handle = await self._observe.dom_element(tab, ref)
            await handle.set_value(value)
            return Effect("Date/time value set and verified.")

        return await actions.run(
            kind=ActionKind.SET_DATE,
            operation=set_date,
            check=check,
        )
