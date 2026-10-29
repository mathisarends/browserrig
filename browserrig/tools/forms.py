from harnessed import Inject, Plugin, tool

from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, ElementOperation

from .execution import Actions, Effect


class FormTools(Plugin):
    @tool(description="Type exact text into a DOM ref; clear replaces its value by default.")
    async def type_text(
        self,
        ref: str,
        text: str,
        clear: bool = True,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def type_text(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await tab.input.move_to(point)
            await actions.element_point(tab=tab, ref=ref, scroll=False)
            await actions.element_call(
                tab=tab, ref=ref, operation=ElementOperation.FOCUS, value=clear
            )
            if clear:
                await tab.input.press_key("Backspace")
            await tab.input.type_text(text)
            return Effect("Text entered.")

        return await actions.run(kind=ActionKind.TYPE, operation=type_text)

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
