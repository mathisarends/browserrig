import asyncio

from browserrig.browser import Tab
from browserrig.core import BrowserError, StaleElement
from browserrig.input import Mouse
from browserrig.observation import ElementHandle, ScrollableElement


async def prepare_element(
    tab: Tab, handle: ElementHandle, mouse: Mouse, *, document_id: str
) -> bool:
    """Execute a backend's wheel plan through normal mouse input, when supported."""
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
