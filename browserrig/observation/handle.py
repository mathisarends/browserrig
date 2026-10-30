from dataclasses import dataclass
from typing import Any

from browserrig.browser.tab import Frame
from browserrig.core.geometry import Bounds, ElementPoint
from browserrig.core.kinds import ElementOperation
from browserrig.scripts import ELEMENT
from browserrig.scripts.models import ElementArgs

from .models import Element, Snapshot


@dataclass(frozen=True, slots=True)
class ElementHandle:
    """An element ref from the latest observation, bound to the frame it currently lives in.

    Methods run in the element's own document; only `locate` returns viewport coordinates.
    """

    frame: Frame
    element: Element
    snapshot: Snapshot

    async def locate(self) -> ElementPoint:
        """Return a hit-tested viewport point and the element's visible bounds."""
        local = ElementPoint.model_validate(
            await self._run(ElementOperation.POINT, clip=self.frame.local_visible)
        )
        x, y = self.frame.transform.to_viewport(local.x, local.y)
        await self.frame.check_point(x, y)
        bounds = (
            self.frame.transform.bounds_to_viewport(local.bounds)
            if local.bounds is not None
            else None
        )
        return ElementPoint(x=x, y=y, bounds=bounds)

    async def bounds(self) -> Bounds:
        """Return the element's layout box in its frame's CSS pixels."""
        return Bounds.model_validate(await self._run(ElementOperation.BOUNDS))

    async def focus(self, *, select_all: bool) -> None:
        await self._run(ElementOperation.FOCUS, select_all)

    async def select(self, option: str) -> None:
        """Choose a native select option by exact label or value."""
        await self._run(ElementOperation.SELECT, option)

    async def set_value(self, value: str) -> None:
        await self._run(ElementOperation.SET_VALUE, value)

    async def upload_files(self, paths: list[str]) -> None:
        node = await self._run(ElementOperation.NODE, by_value=False)
        await self.frame.upload_files(node.object_id, paths)

    async def _run(
        self,
        operation: ElementOperation,
        value: str | bool | None = None,
        *,
        clip: Bounds | None = None,
        by_value: bool = True,
    ) -> Any:
        return await self.frame.run(
            ELEMENT,
            ElementArgs(
                token=self.snapshot.id,
                index=self.element.index,
                operation=operation,
                value=value,
                clip=clip,
            ),
            by_value=by_value,
            user_gesture=True,
        )
