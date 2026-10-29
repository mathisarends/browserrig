from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from cdpify import CdpSession
from cdpify.domains.page import FrameTree
from cdpify.domains.runtime import CallArgument
from cdpify.exceptions import CDPCommandError
from pydantic import BaseModel

from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, Projection
from browserrig.events import BrowserEvent, InputEvent
from browserrig.input import Input, Keyboard, Mouse
from browserrig.scripts import OWNER_HITS, Script, failure
from browserrig.scripts.models import OwnerHitsArgs


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

    @property
    def clip_payload(self) -> dict[str, float] | None:
        return self.local_clip.model_dump() if self.local_clip is not None else None

    async def frame_tree(self) -> FrameTree:
        return await _frame_tree(self.cdp)

    async def upload_files(self, object_id: str, paths: list[str]) -> None:
        try:
            await self.cdp.dom.set_file_input_files(files=paths, object_id=object_id)
        finally:
            await self.cdp.runtime.release_object(object_id=object_id)

    async def run_on_owner[A: BaseModel, R](self, script: Script[A, R], args: A | None = None) -> R:
        """Run with this frame's embedding element as `this`, using the same error policy."""
        assert self.parent is not None and self.owner_id is not None
        cdp = self.parent.cdp
        resolved = await cdp.dom.resolve_node(
            backend_node_id=self.owner_id, execution_context_id=await self.parent.context()
        )
        object_id = resolved.object.object_id
        if object_id is None:
            raise BrowserError("Element frame no longer exists; observe again")
        try:
            return await _call(cdp, script, args, object_id=object_id)
        finally:
            with suppress(CDPCommandError):
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
            hits = await current.run_on_owner(
                OWNER_HITS,
                OwnerHitsArgs(
                    points=tuple(current.parent.projection.inverse(x, y) for x, y in points)
                ),
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

    async def run[A: BaseModel, R](
        self,
        script: Script[A, R],
        args: A | None = None,
        *,
        objects: Sequence[str] = (),
        by_value: bool = True,
        user_gesture: bool = False,
    ) -> R:
        return await _call(
            self.cdp,
            script,
            args,
            objects=objects,
            by_value=by_value,
            user_gesture=user_gesture,
            context_id=await self.context(),
        )


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
        self.input = Input(self.cdp, self.emit)

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
        tree = await self.frame_tree()
        return Frame(tree.frame.id, self.cdp)

    async def frame_tree(self) -> FrameTree:
        return await _frame_tree(self.cdp)

    async def sync_document(self) -> None:
        tree = await self.frame_tree()
        self.document_id, self.url = tree.frame.loader_id, tree.frame.url

    async def go_back(self) -> bool:
        return await self._history(-1)

    async def go_forward(self) -> bool:
        return await self._history(1)

    async def _history(self, offset: int) -> bool:
        history = await self.cdp.page.get_navigation_history()
        index = history.current_index + offset
        if not 0 <= index < len(history.entries):
            return False
        await self.cdp.page.navigate_to_history_entry(entry_id=history.entries[index].id)
        return True

    async def reload(self) -> None:
        await self.cdp.page.reload()

    async def handle_dialog(self, *, accept: bool, text: str = "") -> None:
        await self.cdp.page.handle_java_script_dialog(accept=accept, prompt_text=text)

    async def bring_to_front(self) -> None:
        await self.cdp.page.bring_to_front()

    async def navigate(self, url: str) -> None:
        result = await self.cdp.page.navigate(url=validated_url(url))
        if result.error_text:
            raise BrowserError(f"Navigation failed: {result.error_text}")


async def _frame_tree(cdp: CdpSession) -> FrameTree:
    result = await cdp.page.get_frame_tree()
    return result.frame_tree


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or (parsed.scheme in {"http", "https"} and parsed.hostname):
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


async def _call[A: BaseModel, R](
    cdp: CdpSession,
    script: Script[A, R],
    args: A | None,
    *,
    objects: Sequence[str] = (),
    by_value: bool = True,
    user_gesture: bool = False,
    context_id: int | None = None,
    object_id: str | None = None,
) -> Any:
    payload = script.arguments.model_validate({} if args is None else args)
    result = await cdp.runtime.call_function_on(
        function_declaration=script.declaration,
        execution_context_id=context_id,
        object_id=object_id,
        arguments=[
            CallArgument(value=payload.model_dump(mode="json", by_alias=True)),
            *(CallArgument(object_id=node) for node in objects),
        ],
        return_by_value=by_value,
        await_promise=True,
        user_gesture=user_gesture,
    )
    if result.exception_details:
        raise BrowserError(failure(script, result.exception_details))
    return script.parse(result.result.value) if by_value else result.result
