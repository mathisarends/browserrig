from typing import Annotated

from harnessed import Plugin, ToolError
from harnessed.kernel import needs
from pydantic import Field

from browserrig.browser import Tab
from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.observation import DomElementHandle, DomElements
from browserrig.scripts import TARGET_SCROLL, TargetScrollArgs, TargetScrollResult

from .effects import Effect
from .execution import Actions

type _ScrollDelta = Annotated[float, Field(ge=-10000, le=10000)]


class DomScrollTools(Plugin):
    """Target a DOM page or container independently of pointer position."""

    _actions = needs(Actions)
    _elements = needs(DomElements)

    @tool(
        kind=ActionKind.SCROLL_PAGE,
        description=(
            "Scroll only the outer page, independently of the cursor and nested panels. "
            "delta_y is CSS pixels down (negative up); delta_x is right (negative left). "
            "Reports actual movement or the page boundary/scroll lock. "
            "Use scroll_element to move an inner list, panel or carousel."
        ),
    )
    async def scroll_page(
        self,
        delta_y: _ScrollDelta = 0,
        delta_x: _ScrollDelta = 0,
    ) -> Effect:
        if delta_y == 0 and delta_x == 0:
            raise ToolError("Provide a non-zero delta_y or delta_x")
        return await scroll_page(self._actions.tab, delta_y=delta_y, delta_x=delta_x)

    @tool(
        kind=ActionKind.SCROLL_ELEMENT,
        description=(
            "Scroll only the observed container ref marked scroll(...), independently "
            "of the cursor. delta_y is CSS pixels down (negative up); delta_x is right "
            "(negative left). Stops at its boundary without scrolling ancestors or the page. "
            "Reports actual movement; a ref for a non-scrollable element is rejected. "
            "Use scroll_page for the outer document."
        ),
    )
    async def scroll_element(
        self,
        ref: str,
        delta_y: _ScrollDelta = 0,
        delta_x: _ScrollDelta = 0,
    ) -> Effect:
        if delta_y == 0 and delta_x == 0:
            raise ToolError("Provide a non-zero delta_y or delta_x")
        tab = self._actions.tab
        handle = await self._elements.resolve(tab, ref)
        return await scroll_element(tab, handle, delta_y=delta_y, delta_x=delta_x)


async def scroll_page(tab: Tab, *, delta_x: float, delta_y: float) -> Effect:
    """Scroll the top-level document without routing a wheel through the cursor."""
    frame = await tab.main_frame()
    result = await frame.run(
        TARGET_SCROLL, TargetScrollArgs(delta_x=delta_x, delta_y=delta_y, page=True)
    )
    return _scroll_effect(tab, result, "Page")


async def scroll_element(
    tab: Tab, handle: DomElementHandle, *, delta_x: float, delta_y: float
) -> Effect:
    """Scroll only the addressed DOM container, without revealing or bubbling."""
    result = await handle.run(
        TARGET_SCROLL, TargetScrollArgs(delta_x=delta_x, delta_y=delta_y)
    )
    if not result.scrollable:
        raise BrowserError(
            "Ref is not a scrollable container; use a container ref marked scroll(...), "
            "or scroll_page for the outer document"
        )
    return _scroll_effect(tab, result, "Element")


def _scroll_effect(tab: Tab, result: TargetScrollResult, label: str) -> Effect:
    before, after = result.before, result.after
    position = f"x={after.x:g}, y={after.y:g}"
    if before == after:
        reason = (
            f"{label} scrolling is disabled for the requested axis."
            if result.blocked
            else f"{label} boundary reached."
        )
        return Effect(f"{label} did not move ({position}). {reason}")
    tab.layout_changed()
    return Effect(
        f"{label} scrolled from x={before.x:g}, y={before.y:g} to {position}."
    )
