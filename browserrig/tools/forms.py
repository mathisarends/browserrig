from harnessed import Inject, Plugin, tool

from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, ElementOperation

from .execution import Actions, Effect


class FormTools(Plugin):
    @tool(description="Select an exact option label or value in a native select element.")
    async def select_option(
        self,
        ref: str,
        value: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def select(tab: Tab) -> Effect:
            await actions.element_call(
                tab=tab,
                ref=ref,
                operation=ElementOperation.SELECT,
                value=value,
            )
            return Effect("Option selected.")

        return await actions.run(
            kind=ActionKind.SELECT,
            operation=select,
        )

    @tool(description="Set a native date/time input in its HTML format, such as YYYY-MM-DD.")
    async def set_date(
        self,
        ref: str,
        value: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def set_date(tab: Tab) -> Effect:
            _, element = await actions.observe.element(tab, ref)
            if element.input_type not in {"date", "time", "datetime-local", "month", "week"}:
                raise ValueError("Element is not a native date/time input")
            await actions.element_call(
                tab=tab,
                ref=ref,
                operation=ElementOperation.SET_VALUE,
                value=value,
            )
            return Effect("Date/time value set and verified.")

        return await actions.run(
            kind=ActionKind.TYPE,
            operation=set_date,
        )
