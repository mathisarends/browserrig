import json
from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.observation import DomElements
from browserrig.scripts import SelectionResult

from .effects import Effect
from .execution import Actions


class FormTools(Plugin):
    # Batching form fields is covered by the action-chain instructions of Actions.
    _elements = needs(DomElements)
    _actions = needs(Actions)

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
        await self._elements.resolve(tab, ref)
        point = await self._actions.element_point(ref=ref)
        await self._actions.browser.input.mouse.move_to(point)
        current = await self._actions.element_point(ref=ref, scroll=False)
        if (current.x, current.y) != (point.x, point.y):
            await self._actions.browser.input.mouse.move_to(current)
        handle = await self._elements.resolve(tab, ref)
        await handle.select(value)
        return Effect("Option selected.", prepared_scroll=point.scrolled)

    @tool(
        kind=ActionKind.SELECT_OPTIONS,
        chainable=True,
        description=(
            "Replace the selected set of a native multiple select. Each value must "
            "match one exact option label or value unambiguously. Empty values clears "
            "the selection. Validates the whole set before mutation and verifies it "
            "after input/change handlers. Use select_option for single selects."
        ),
    )
    async def select_options(
        self,
        ref: str,
        values: Annotated[list[str], Field(max_length=1000)],
    ) -> Effect:
        tab = self._actions.tab
        handle = await self._elements.resolve(tab, ref)
        await handle.validate_options(values)
        point = await self._actions.element_point(ref=ref)
        await self._actions.browser.input.mouse.move_to(point)
        current = await self._actions.element_point(ref=ref, scroll=False)
        if (current.x, current.y) != (point.x, point.y):
            await self._actions.browser.input.mouse.move_to(current)
        handle = await self._elements.resolve(tab, ref)
        await handle.validate_options(values)
        result = await handle.select_options(values)
        selected = _selection(result)
        if not result.verified:
            raise BrowserError(
                f"{result.reason} Observed selection: {selected}. "
                "Inspect the current page before retrying."
            )
        return Effect(
            f"Selected {len(result.selected)} option(s) and verified: {selected}.",
            prepared_scroll=point.scrolled,
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
    ) -> Effect:
        tab = self._actions.tab
        handle = await self._elements.resolve(tab, ref)
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
        handle = await self._elements.resolve(tab, ref)
        await handle.set_value(value)
        return Effect(
            "Date/time value set and verified.", prepared_scroll=point.scrolled
        )


def _selection(result: SelectionResult) -> str:
    shown = [
        {"label": option.label[:100], "value": option.value[:100]}
        for option in result.selected[:10]
    ]
    text = json.dumps(shown, ensure_ascii=False)
    if len(result.selected) > len(shown):
        text += f" (+{len(result.selected) - len(shown)} additional selected options)"
    return text
