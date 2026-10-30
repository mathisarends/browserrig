from harnessed import Inject, Plugin, ToolResult

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.kinds import ActionKind
from browserrig.core.tools import browser_tool as tool
from browserrig.observation.plugin import Observe, has_dom_refs

from .execution import Actions, Effect


class FormTools(Plugin, needs=(Actions, Observe)):
    _observe: Inject[Observe]

    @tool(
        kind=ActionKind.SELECT,
        chainable=True,
        enabled=has_dom_refs,
        description="Select an exact option label or value in a native select element.",
    )
    async def select_option(
        self,
        ref: str,
        value: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def select(tab: Tab) -> Effect:
            await actions.element_point(tab=tab, ref=ref)
            await (await self._observe.element(tab, ref)).select(value)
            return Effect("Option selected.")

        return await actions.run(
            kind=ActionKind.SELECT,
            operation=select,
        )

    @tool(
        kind=ActionKind.SET_DATE,
        chainable=True,
        enabled=has_dom_refs,
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
            handle = await self._observe.element(tab, ref)
            if handle.element.input_type not in {"date", "time", "datetime-local", "month", "week"}:
                raise BrowserError("Element is not a native date/time input")

        async def set_date(tab: Tab) -> Effect:
            await actions.element_point(tab=tab, ref=ref)
            await (await self._observe.element(tab, ref)).set_value(value)
            return Effect("Date/time value set and verified.")

        return await actions.run(
            kind=ActionKind.SET_DATE,
            operation=set_date,
            check=check,
        )
