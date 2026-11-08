from harnessed import Instructions, Plugin, SystemPrompt
from harnessed.kernel import needs

from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.observation import BrowserPerception

from .effects import Effect
from .execution import Actions

_INSTRUCTIONS = Instructions(
    title="Form filling",
    text=(
        "On forms, prefer multiple ordered tool calls in one response for independent "
        "fields with known refs and values. Ordinary value updates and automatic reveal "
        "scrolling do not need a roundtrip per field. Observe before deciding a later "
        "value or submission based on new suggestions, options or validation results."
    ),
)


class FormTools(Plugin):
    _observe = needs(BrowserPerception)
    _actions = needs(Actions)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @tool(
        kind=ActionKind.SELECT,
        chainable=True,
        description="Select an exact option label or value in a native select element.",
    )
    async def select_option(
        self,
        ref: str,
        value: str,
    ) -> Effect:
        tab = self._actions.tab
        await self._observe.dom_element(tab, ref)
        point = await self._actions.element_point(ref=ref)
        await self._actions.browser.input.mouse.move_to(point)
        current = await self._actions.element_point(ref=ref, scroll=False)
        if (current.x, current.y) != (point.x, point.y):
            await self._actions.browser.input.mouse.move_to(current)
        handle = await self._observe.dom_element(tab, ref)
        await handle.select(value)
        return Effect("Option selected.", prepared_scroll=point.scrolled)

    @tool(
        kind=ActionKind.SET_DATE,
        chainable=True,
        description="Set a native date/time input in its HTML format, such as YYYY-MM-DD.",
    )
    async def set_date(
        self,
        ref: str,
        value: str,
    ) -> Effect:
        tab = self._actions.tab
        handle = await self._observe.dom_element(tab, ref)
        if handle.element.input_type not in {
            "date",
            "time",
            "datetime-local",
            "month",
            "week",
        }:
            raise BrowserError("Element is not a native date/time input")
        point = await self._actions.element_point(ref=ref)
        await self._actions.browser.input.mouse.move_to(point)
        current = await self._actions.element_point(ref=ref, scroll=False)
        if (current.x, current.y) != (point.x, point.y):
            await self._actions.browser.input.mouse.move_to(current)
        handle = await self._observe.dom_element(tab, ref)
        await handle.set_value(value)
        return Effect(
            "Date/time value set and verified.", prepared_scroll=point.scrolled
        )
