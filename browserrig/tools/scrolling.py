import asyncio
from collections.abc import Callable

from harnessed.tracing import traced

from browserrig.browser import Tab
from browserrig.core import BrowserError, StaleElement
from browserrig.input import Mouse
from browserrig.observation import DomElementHandle, ElementHandle, ScrollableElement
from browserrig.scripts import TARGET_SCROLL, TargetScrollArgs, TargetScrollResult

from .effects import Effect


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


@traced
async def prepare_element(
    tab: Tab,
    handle: ElementHandle,
    mouse: Mouse,
    *,
    document_id: str,
    report: Callable[[str], None] | None = None,
) -> bool:
    """Reveal DOM targets directly; preserve custom backends' wheel input protocol."""
    if isinstance(handle, DomElementHandle):
        return await _reveal_dom(tab, handle, report=report)
    if not isinstance(handle, ScrollableElement):
        return False
    scrolled = False
    previous = None
    stalled = 0
    async with asyncio.timeout(20):
        for _ in range(32):
            await tab.sync_document()
            if tab.document_id != document_id:
                raise StaleElement(
                    "Document changed while scrolling; use refs from the next observation"
                )
            step = await handle.scroll_step()
            if step is None:
                return scrolled
            stalled = stalled + 1 if step.key == previous else 0
            if stalled >= 2:
                break
            previous = step.key
            await mouse.scroll(
                point=step.point, delta_x=step.delta_x, delta_y=step.delta_y
            )
            scrolled = True
            await asyncio.sleep(0.05)
    raise BrowserError(
        "Element could not be brought into view using wheel input; try another way to reach it"
    )


async def _reveal_dom(
    tab: Tab, handle: DomElementHandle, *, report: Callable[[str], None] | None
) -> bool:
    scrolled = False
    stalled = 0
    async with asyncio.timeout(20):
        for _ in range(32):
            step = await handle.reveal_step()
            if step is None:
                return scrolled
            if step.changed:
                scrolled = True
                stalled = 0
                tab.layout_changed()
                if report is not None:
                    positions = ", ".join(
                        f"{axis}: {getattr(step.before, axis):g} → "
                        f"{getattr(step.after, axis):g}"
                        for axis in ("x", "y")
                        if getattr(step.before, axis) != getattr(step.after, axis)
                    )
                    report(
                        f"Auto-scrolled {step.container} to reveal "
                        f"[{handle.element.ref}] ({positions})."
                    )
            else:
                stalled += 1
                if stalled >= 2:
                    break
            await asyncio.sleep(0.05)
    raise BrowserError(
        "Automatic reveal stalled or exceeded its step limit; inspect the current "
        "page and scroll the relevant container explicitly."
    )


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
