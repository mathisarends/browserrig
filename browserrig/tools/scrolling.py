import asyncio
from dataclasses import replace

from browserrig.browser.tab import Frame, Tab
from browserrig.core.errors import BrowserError, StaleElement
from browserrig.core.geometry import Point
from browserrig.observation.handle import ElementHandle
from browserrig.scripts import SCROLL, SCROLL_OWNER
from browserrig.scripts.models import OwnerScrollArgs, ScrollArgs, ScrollPlan


async def _plan(handle: ElementHandle) -> tuple[Frame, ScrollPlan] | None:
    frame = handle.frame
    ancestors: list[Frame] = []
    current = frame
    while current.parent is not None:
        ancestors.append(current)
        current = current.parent
    target = None
    if ancestors:
        target = frame.transform.bounds_to_viewport(await handle.bounds())
    for child in reversed(ancestors):
        parent = child.parent
        assert parent is not None
        clip = parent.local_visible
        assert target is not None
        local = parent.transform.bounds_to_local(target)
        raw = await child.run_on_owner(
            SCROLL_OWNER, OwnerScrollArgs(clip=clip, target_bounds=local)
        )
        if raw is not None:
            return parent, raw
    clip = frame.local_visible
    raw = await frame.run(
        SCROLL, ScrollArgs(token=handle.snapshot.id, index=handle.element.index, clip=clip)
    )
    return (frame, raw) if raw is not None else None


async def prepare_element(tab: Tab, handle: ElementHandle) -> bool:
    """Bring a DOM target into a comfortable view using native wheel input, outer frames first."""
    scrolled = False
    previous = None
    stalled = 0
    async with asyncio.timeout(20):
        for _ in range(32):
            await tab.sync_document()
            if tab.document_id != handle.snapshot.document_id:
                raise StaleElement("Document changed while scrolling; observe again")
            frame = next((item for item in await tab.frames() if item.id == handle.frame.id), None)
            if frame is None:
                raise StaleElement("Element frame no longer exists; observe again")
            handle = replace(handle, frame=frame)
            planned = await _plan(handle)
            if planned is None:
                return scrolled
            owner, plan = planned
            signature = (owner.id, plan.model_dump_json())
            stalled = stalled + 1 if signature == previous else 0
            if stalled >= 2:
                break
            previous = signature
            x, y = owner.transform.to_viewport(plan.x, plan.y)
            await owner.check_point(x, y)
            await tab.mouse.scroll(
                point=Point(x=x, y=y), delta_x=plan.delta_x, delta_y=plan.delta_y
            )
            scrolled = True
            await asyncio.sleep(0.05)
    raise BrowserError("Element could not be brought into view using wheel input; observe again")
