import asyncio
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from browserrig.browser import Frame, Tab
from browserrig.core import (
    Bounds,
    BrowserError,
    ElementOperation,
    ElementPoint,
    Point,
    StaleElement,
)
from browserrig.scripts import (
    ELEMENT,
    SCROLL,
    SCROLL_OWNER,
    ElementArgs,
    OwnerScrollArgs,
    Script,
    ScrollArgs,
    ScrollPlan,
    TextState,
)

from .models import Element, Snapshot
from .references import RevealStep, ScrollStep


@dataclass(frozen=True, slots=True)
class DomElementHandle:
    """An element from the latest observation, bound to the frame it lives in.

    Methods run in the element's own document; only `locate` returns viewport coordinates.
    """

    frame: Frame
    element: Element
    snapshot: Snapshot
    tab: Tab

    async def locate(self, *, aim: tuple[float, float] | None = None) -> ElementPoint:
        """Return a hit-tested viewport point and the element's visible bounds.

        `aim` is a preferred spot as fractions of the visible box; when something
        covers it, the point falls back to the middle or near a corner.
        """
        try:
            local = ElementPoint.model_validate(
                await self._run(
                    ElementOperation.POINT, clip=self.frame.local_visible, aim=aim
                )
            )
        except BrowserError as error:
            if str(error) != "ELEMENT_BLOCKED":
                raise
            details = (
                "The target could not be hit-tested; layout diagnostics unavailable."
            )
            try:
                async with asyncio.timeout(0.5):
                    details = await self.run(
                        ELEMENT,
                        ElementArgs(
                            operation=ElementOperation.DIAGNOSE,
                            clip=self.frame.local_visible,
                        ),
                    )
            except (BrowserError, TimeoutError):
                pass
            raise BrowserError(
                f"ELEMENT_BLOCKED: target ref {self.element.ref}. {details}"
            ) from error
        x, y = self.frame.transform.to_viewport(local.x, local.y)
        try:
            await self.frame.check_point(x, y)
        except BrowserError as error:
            if str(error) != "ELEMENT_BLOCKED":
                raise
            raise BrowserError(
                f"ELEMENT_BLOCKED: target ref {self.element.ref} is hit-testable inside "
                f"frame {self.frame.id}, but its viewport point ({x:g}, {y:g}) is "
                "covered or clipped in an embedding document. Inspect the outer page."
            ) from error
        bounds = (
            self.frame.transform.bounds_to_viewport(local.bounds)
            if local.bounds is not None
            else None
        )
        return ElementPoint(x=x, y=y, bounds=bounds)

    async def bounds(self) -> Bounds:
        """Return the element's layout box in its frame's CSS pixels."""
        return Bounds.model_validate(await self._run(ElementOperation.BOUNDS))

    async def scroll_step(self) -> ScrollStep | None:
        """Plan one wheel input without scrolling."""
        planned = await self._scroll_plan(apply=False)
        if planned is None:
            return None
        owner, plan = planned
        x, y = owner.transform.to_viewport(plan.x, plan.y)
        await owner.check_point(x, y)
        return ScrollStep(
            point=Point(x=x, y=y),
            delta_x=plan.delta_x,
            delta_y=plan.delta_y,
            key=f"{owner.id}:{plan.model_dump_json()}",
        )

    async def reveal_step(self) -> RevealStep | None:
        """Scroll one exact DOM container and return its measured before/after position."""
        planned = await self._scroll_plan(apply=True)
        if planned is None:
            return None
        owner, plan = planned
        assert plan.after_x is not None and plan.after_y is not None
        step = RevealStep(
            frame_id=owner.id,
            container="frame page"
            if owner.parent is not None and plan.container == "page"
            else plan.container,
            before=Point(x=plan.scroll_x, y=plan.scroll_y),
            after=Point(x=plan.after_x, y=plan.after_y),
        )
        if step.changed:
            self.tab.layout_changed()
        return step

    async def focus(self, *, select_all: bool) -> None:
        await self._run(ElementOperation.FOCUS, select_all)

    async def is_focused(self) -> bool:
        """Whether this target retains focus, including its embedding frame chain."""
        if self.tab.document_id != self.snapshot.document_id:
            return False
        if not await self.run(ELEMENT, ElementArgs(operation=ElementOperation.FOCUSED)):
            return False
        frame = self.frame
        while frame.parent is not None:
            if not await frame.run_on_owner(
                ELEMENT, ElementArgs(operation=ElementOperation.FOCUSED)
            ):
                return False
            frame = frame.parent
        return True

    async def select(self, option: str) -> None:
        """Choose a native select option by exact label or value."""
        await self._run(ElementOperation.SELECT, option)

    async def set_value(self, value: str) -> None:
        await self._run(ElementOperation.SET_VALUE, value)

    async def text_state(self) -> TextState | None:
        """Read a native text field and selection; never read password values."""
        state = await self._run(ElementOperation.TEXT_STATE)
        return None if state is None else TextState.model_validate(state)

    async def upload_files(self, paths: list[str]) -> None:
        await self.frame.upload_files(self.element.backend_id, paths)

    async def run[A: BaseModel, R](
        self, script: Script[A, R], args: A | None = None, *, user_gesture: bool = False
    ) -> R:
        """Run a script with this element as `this` in its own document."""
        return await self.frame.run_on_node(
            self.element.backend_id, script, args, user_gesture=user_gesture
        )

    async def _scroll_plan(self, *, apply: bool) -> tuple[Frame, ScrollPlan] | None:
        await self.tab.sync_document()
        if self.tab.document_id != self.snapshot.document_id:
            raise StaleElement(
                "Document changed while scrolling; use refs from the next observation"
            )
        frame = next(
            (item for item in await self.tab.frames() if item.id == self.frame.id), None
        )
        if frame is None:
            raise StaleElement(
                "Element frame no longer exists; use refs from the next observation"
            )
        return await _plan(replace(self, frame=frame), apply=apply)

    async def _run(
        self,
        operation: ElementOperation,
        value: str | bool | None = None,
        *,
        clip: Bounds | None = None,
        aim: tuple[float, float] | None = None,
    ) -> Any:
        return await self.run(
            ELEMENT,
            ElementArgs(operation=operation, value=value, clip=clip, aim=aim),
            user_gesture=True,
        )


@dataclass(frozen=True, slots=True)
class DomReferences:
    """Resolve the DOM addresses carried by the current observation's element data."""

    async def resolve(self, tab: Tab, snapshot: Snapshot, ref: str) -> DomElementHandle:
        element = snapshot.element(ref)
        if not isinstance(element, Element):
            raise BrowserError(
                "Target is not a DOM element; the capture strategy must supply References"
            )
        for frame in await tab.frames():
            if frame.id == element.frame_id:
                return DomElementHandle(frame, element, snapshot, tab)
        raise StaleElement(
            "Element frame no longer exists; use refs from the next observation"
        )


async def _plan(
    handle: DomElementHandle, *, apply: bool
) -> tuple[Frame, ScrollPlan] | None:
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
            SCROLL_OWNER, OwnerScrollArgs(clip=clip, target_bounds=local, apply=apply)
        )
        if raw is not None:
            return parent, raw
    clip = frame.local_visible
    raw = await handle.run(SCROLL, ScrollArgs(clip=clip, apply=apply))
    return (frame, raw) if raw is not None else None
