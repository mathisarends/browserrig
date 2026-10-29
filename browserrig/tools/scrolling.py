import asyncio
from importlib.resources import files

from browserrig.browser.base import Browser
from browserrig.browser.errors import BrowserError, StaleElement
from browserrig.browser.geometry import Bounds
from browserrig.browser.models import Point
from browserrig.browser.tab import Frame, Tab
from browserrig.kinds import ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT
from browserrig.observation.models import Element, Snapshot

SCROLL_SCRIPT = (
    files("browserrig.observation").joinpath("scripts/scroll.js").read_text(encoding="utf-8")
)


class _ScrollPlan(Point):
    delta_x: float
    delta_y: float
    scroll_x: float
    scroll_y: float


async def _plan(
    frame: Frame, snapshot: Snapshot, element: Element
) -> tuple[Frame, _ScrollPlan] | None:
    ancestors: list[Frame] = []
    current = frame
    while current.parent is not None:
        ancestors.append(current)
        current = current.parent
    target = None
    if ancestors:
        box = Bounds.model_validate(
            await frame.call(ELEMENT_SCRIPT, snapshot.id, element.index, ElementOperation.BOUNDS)
        )
        target = frame.projection.box(box)
    for child in reversed(ancestors):
        parent = child.parent
        assert parent is not None
        clip = parent.local_clip.model_dump() if parent.local_clip is not None else None
        assert target is not None
        local = parent.projection.local_box(target).model_dump()
        raw = await child.owner_call(SCROLL_SCRIPT, False, 0, clip, local)
        if raw is not None:
            return parent, _ScrollPlan.model_validate(raw)
    clip = frame.local_clip.model_dump() if frame.local_clip is not None else None
    raw = await frame.call(SCROLL_SCRIPT, snapshot.id, element.index, clip)
    return (frame, _ScrollPlan.model_validate(raw)) if raw is not None else None


async def prepare_element(browser: Browser, tab: Tab, snapshot: Snapshot, element: Element) -> bool:
    """Bring a DOM target into a comfortable view using native wheel input, outer frames first."""
    scrolled = False
    previous = None
    stalled = 0
    async with asyncio.timeout(20):
        for _ in range(32):
            await tab.main_frame()
            if tab.document_id != snapshot.document_id:
                raise StaleElement("Document changed while scrolling; observe again")
            frame = next(
                (item for item in await browser.frames(tab) if item.id == element.frame_id), None
            )
            if frame is None:
                raise StaleElement("Element frame no longer exists; observe again")
            planned = await _plan(frame, snapshot, element)
            if planned is None:
                return scrolled
            owner, plan = planned
            signature = (owner.id, plan.model_dump_json())
            stalled = stalled + 1 if signature == previous else 0
            if stalled >= 2:
                break
            previous = signature
            x, y = owner.projection.point(plan.x, plan.y)
            await owner.check_point(x, y)
            await tab.mouse.scroll(
                point=Point(x=x, y=y), delta_x=plan.delta_x, delta_y=plan.delta_y
            )
            scrolled = True
            await asyncio.sleep(0.05)
    raise BrowserError("Element could not be brought into view using wheel input; observe again")
