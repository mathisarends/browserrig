from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from browserrig.browser import Frame
from browserrig.core.geometry import Bounds, ElementPoint
from browserrig.core.kinds import ElementOperation
from browserrig.scripts import ELEMENT, ElementArgs, Script

from .models import Element, Snapshot


@dataclass(frozen=True, slots=True)
class ElementHandle:
    """An element from the latest observation, bound to the frame it lives in.

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
        await self.frame.upload_files(self.element.backend_id, paths)

    async def run[A: BaseModel, R](
        self, script: Script[A, R], args: A | None = None, *, user_gesture: bool = False
    ) -> R:
        """Run a script with this element as `this` in its own document."""
        return await self.frame.run_on_node(
            self.element.backend_id, script, args, user_gesture=user_gesture
        )

    async def _run(
        self,
        operation: ElementOperation,
        value: str | bool | None = None,
        *,
        clip: Bounds | None = None,
    ) -> Any:
        return await self.run(
            ELEMENT,
            ElementArgs(operation=operation, value=value, clip=clip),
            user_gesture=True,
        )
