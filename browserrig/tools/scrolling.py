import asyncio
from collections.abc import Callable

from harnessed.tracing import traced

from browserrig.browser import Tab
from browserrig.core import BrowserError, StaleElement
from browserrig.input import Mouse
from browserrig.observation import ElementHandle, RevealableElement, ScrollableElement


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
    if isinstance(handle, RevealableElement):
        return await handle.reveal(report=report)
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
