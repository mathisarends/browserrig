from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from cdpify import CdpSession
from cdpify.domains.runtime import CallArgument

from browserrig.events import BrowserEvent, InputEvent
from browserrig.input import Input, Keyboard, Mouse

from .errors import BrowserError
from .geometry import Bounds, Projection


@dataclass(frozen=True, slots=True)
class Frame:
    """A CDP page frame: the top-level document or one embedded iframe.

    Its isolated JavaScript world belongs to that frame, not to browser focus.
    Its projection maps frame-local CSS pixels to the containing tab's viewport.
    """

    id: str
    cdp: CdpSession
    projection: Projection = Projection()
    parent: Frame | None = None
    owner_id: int | None = None

    @property
    def x(self) -> float:
        return self.projection.x

    @property
    def y(self) -> float:
        return self.projection.y

    @property
    def local_clip(self) -> Bounds | None:
        clip = self.projection.clip
        return self.projection.local_box(clip) if clip is not None else None

    async def owner_call(self, function: str, *arguments: object) -> Any:
        """Inspect the embedding element in its parent's isolated world."""
        assert self.parent is not None and self.owner_id is not None
        cdp = self.parent.cdp
        resolved = await cdp.dom.resolve_node(
            backend_node_id=self.owner_id, execution_context_id=await self.parent.context()
        )
        object_id = resolved.object.object_id
        if object_id is None:
            raise BrowserError("Element frame no longer exists; observe again")
        try:
            result = await cdp.runtime.call_function_on(
                object_id=object_id,
                function_declaration=function,
                arguments=[CallArgument(value=value) for value in arguments],
                return_by_value=True,
            )
            if result.exception_details:
                raise BrowserError("Frame owner could not be inspected")
            return result.result.value
        finally:
            await cdp.runtime.release_object(object_id=object_id)

    async def check_point(self, x: float, y: float) -> None:
        """A child hit test cannot see blockers in ancestor documents."""
        if not (await self.visible_points(((x, y),)))[0]:
            raise BrowserError("ELEMENT_BLOCKED")

    async def visible_points(self, points: tuple[tuple[float, float], ...]) -> tuple[bool, ...]:
        visible = [True] * len(points)
        current = self
        while current.parent is not None:
            clip = current.projection.clip
            hits = await current.owner_call(
                """function(points) {
                    return points.map(([x, y]) => {
                        let root = this.getRootNode(), target = this;
                        while (root) {
                            const hit = root.elementFromPoint(x, y);
                            if (hit !== target) { return false; }
                            target = root.host;
                            root = target?.getRootNode();
                        }
                        return true;
                    });
                }""",
                [current.parent.projection.inverse(x, y) for x, y in points],
            )
            visible = [
                before and hit and (clip is None or clip.contains(*point))
                for before, hit, point in zip(visible, hits, points, strict=True)
            ]
            current = current.parent
        return tuple(visible)

    async def context(self) -> int:
        result = await self.cdp.page.create_isolated_world(
            frame_id=self.id, world_name="browserrig"
        )
        return result.execution_context_id

    async def evaluate(self, expression: str) -> Any:
        result = await self.cdp.runtime.evaluate(
            expression=expression,
            context_id=await self.context(),
            return_by_value=True,
            await_promise=True,
        )
        if result.exception_details:
            raise BrowserError("Page script failed in the isolated browserrig world")
        return result.result.value

    async def call(self, function: str, *arguments: object, by_value: bool = True) -> Any:
        result = await self.cdp.runtime.call_function_on(
            function_declaration=function,
            execution_context_id=await self.context(),
            arguments=[CallArgument(value=value) for value in arguments],
            return_by_value=by_value,
            await_promise=True,
            user_gesture=True,
        )
        if result.exception_details:
            detail = result.exception_details.exception
            message = detail.description if detail else result.exception_details.text
            # Scripts use fixed error codes; never expose arbitrary page exceptions.
            for code in (
                "STALE_ELEMENT",
                "ELEMENT_BLOCKED",
                "ELEMENT_DISABLED",
                "NOT_EDITABLE",
                "OPTION_NOT_FOUND",
                "NOT_A_SELECT",
                "INVALID_VALUE",
            ):
                if code in (message or ""):
                    raise BrowserError(code)
            raise BrowserError("Element operation failed in the page")
        return result.result.value if by_value else result.result


class Tab:
    def __init__(
        self,
        target_id: str,
        cdp: CdpSession,
        *,
        emit: Callable[[BrowserEvent | InputEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.id = target_id
        self.cdp = cdp
        self.document_id = ""
        self.url = "about:blank"
        self.title = ""
        self.dialog: tuple[str, str] | None = None
        self.closed = False
        self.changed = asyncio.Event()
        self.frame_limitations: tuple[str, ...] = ()
        self._emit = emit
        self.input = Input(self)

    @property
    def mouse(self) -> Mouse:
        return self.input.mouse

    @property
    def keyboard(self) -> Keyboard:
        return self.input.keyboard

    async def emit(self, event: BrowserEvent | InputEvent) -> None:
        if self._emit is not None:
            await self._emit(replace(event, target_id=self.id, document_id=self.document_id))

    async def main_frame(self) -> Frame:
        tree = await self.cdp.page.get_frame_tree()
        self.document_id = tree.frame_tree.frame.loader_id
        self.url = tree.frame_tree.frame.url
        return Frame(tree.frame_tree.frame.id, self.cdp)

    async def evaluate(self, expression: str) -> Any:
        return await (await self.main_frame()).evaluate(expression)

    async def navigate(self, url: str) -> None:
        result = await self.cdp.page.navigate(url=validated_url(url))
        if result.error_text:
            raise BrowserError(f"Navigation failed: {result.error_text}")

    async def press_key(
        self,
        key: str,
        *,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> None:
        """Dispatch input to this tab's page session, never to browser chrome or the OS."""
        await self.keyboard.press_key(
            key,
            hold_control=hold_control,
            hold_shift=hold_shift,
            hold_alt=hold_alt,
            hold_meta=hold_meta,
        )


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or parsed.scheme in {"http", "https"} and parsed.hostname:
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


def script_call(script: str, arguments: dict[str, object]) -> str:
    return f"({script})({json.dumps(arguments, ensure_ascii=True)})"
