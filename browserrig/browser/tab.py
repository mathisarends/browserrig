from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from cdpify import CdpSession
from cdpify.domains.page import (
    FrameNavigatedEvent,
    FrameTree,
    JavascriptDialogClosedEvent,
    JavascriptDialogOpeningEvent,
    NavigatedWithinDocumentEvent,
)
from cdpify.domains.runtime import CallArgument, RemoteObject
from cdpify.exceptions import CDPCommandError
from pydantic import BaseModel

from browserrig.browser.screen import ScreenRecorder
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, FrameTransform, Point
from browserrig.core.kinds import CursorStyle
from browserrig.events import (
    BrowserEvent,
    DialogHandledEvent,
    DialogOpenedEvent,
    LiveEvent,
    NavigationCommittedEvent,
)
from browserrig.input import Input, Keyboard, Mouse
from browserrig.scripts import CURSOR, OWNER_HITS, Script, failure
from browserrig.scripts.models import CursorArgs, OwnerHitsArgs

from .worlds import Worlds

# A cursor shape is presentation only and must never hold up input.
_CURSOR_PROBE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class Frame:
    """A CDP page frame: the top-level document or one embedded iframe.

    Its isolated JavaScript world belongs to that frame, not to browser focus.
    `transform` maps frame-local CSS pixels to the tab's viewport; `visible` is the
    part of the frame left unclipped by its ancestors, in viewport pixels.
    """

    id: str
    cdp: CdpSession
    transform: FrameTransform = FrameTransform()
    visible: Bounds | None = None
    parent: Frame | None = None
    owner_id: int | None = None
    document_id: str = ""
    worlds: Worlds = field(default_factory=Worlds, repr=False, compare=False)

    @property
    def local_visible(self) -> Bounds | None:
        """The visible area in this frame's own CSS pixels, for in-page scripts."""
        return self.transform.bounds_to_local(self.visible) if self.visible is not None else None

    async def frame_tree(self) -> FrameTree:
        return await _frame_tree(self.cdp)

    async def upload_files(self, backend_node_id: int, paths: list[str]) -> None:
        try:
            await self.cdp.dom.set_file_input_files(files=paths, backend_node_id=backend_node_id)
        except CDPCommandError as error:
            raise BrowserError("STALE_ELEMENT") from error

    async def run_on_node[A: BaseModel, R](
        self,
        backend_node_id: int,
        script: Script[A, R],
        args: A | None = None,
        *,
        by_value: bool = True,
        user_gesture: bool = False,
    ) -> R:
        """Run with one of this frame's DOM nodes as `this`, resolved by backend node id."""
        return await self.worlds.run(
            self.cdp,
            self.id,
            self.document_id,
            lambda context: _call_on_node(
                self.cdp,
                backend_node_id,
                script,
                args,
                context,
                by_value=by_value,
                user_gesture=user_gesture,
            ),
        )

    async def run_on_owner[A: BaseModel, R](self, script: Script[A, R], args: A | None = None) -> R:
        """Run with this frame's embedding element as `this`, using the same error policy."""
        assert self.parent is not None and self.owner_id is not None
        try:
            return await self.parent.run_on_node(self.owner_id, script, args)
        except BrowserError as error:
            if str(error) == "STALE_ELEMENT":
                raise BrowserError("Element frame no longer exists; observe again") from error
            raise

    async def check_point(self, x: float, y: float) -> None:
        """A child hit test cannot see blockers in ancestor documents."""
        if not (await self.visible_points(((x, y),)))[0]:
            raise BrowserError("ELEMENT_BLOCKED")

    async def visible_points(self, points: tuple[tuple[float, float], ...]) -> tuple[bool, ...]:
        visible = [True] * len(points)
        current = self
        while current.parent is not None:
            visible_area = current.visible
            hits = await current.run_on_owner(
                OWNER_HITS,
                OwnerHitsArgs(
                    points=tuple(current.parent.transform.to_local(x, y) for x, y in points)
                ),
            )
            visible = [
                before and hit and (visible_area is None or visible_area.contains(*point))
                for before, hit, point in zip(visible, hits, points, strict=True)
            ]
            current = current.parent
        return tuple(visible)

    async def context(self) -> int:
        return await self.worlds.context(self.cdp, self.id, self.document_id)

    async def run[A: BaseModel, R](
        self,
        script: Script[A, R],
        args: A | None = None,
        *,
        objects: Sequence[str] = (),
        by_value: bool = True,
        user_gesture: bool = False,
    ) -> R:
        return await self.worlds.run(
            self.cdp,
            self.id,
            self.document_id,
            lambda context: _call(
                self.cdp,
                script,
                args,
                objects=objects,
                by_value=by_value,
                user_gesture=user_gesture,
                context_id=context,
            ),
            retry=not objects,
        )


type FrameDiscovery = Callable[[Tab], Awaitable[tuple[tuple[Frame, ...], tuple[str, ...]]]]


class Tab:
    def __init__(
        self,
        target_id: str,
        cdp: CdpSession,
        *,
        emit: Callable[[BrowserEvent | LiveEvent], Awaitable[None]] | None = None,
        worlds: Worlds | None = None,
        discover_frames: FrameDiscovery | None = None,
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
        self.worlds = worlds if worlds is not None else Worlds()
        self._emit = emit
        self._discover_frames = discover_frames
        self._layout_revision = 0
        self._frames_key: tuple[str, str, int] | None = None
        self._frames: tuple[Frame, ...] = ()
        self.input = Input(
            self.cdp,
            self.emit,
            layout_changed=self.invalidate_frames,
            cursor_style=self.cursor_style,
        )
        self.screen = ScreenRecorder(self.cdp)

    @property
    def mouse(self) -> Mouse:
        return self.input.mouse

    @property
    def keyboard(self) -> Keyboard:
        return self.input.keyboard

    async def emit(self, event: BrowserEvent | LiveEvent) -> None:
        if self._emit is not None:
            await self._emit(replace(event, target_id=self.id, document_id=self.document_id))

    async def cursor_style(self, point: Point) -> CursorStyle | None:
        """Return the CSS cursor under a viewport point, or None when the page cannot say."""
        if self._emit is None or self.dialog is not None:
            return None
        try:
            async with asyncio.timeout(_CURSOR_PROBE_SECONDS):
                frame = await self.main_frame()
                style = await frame.run(CURSOR, CursorArgs(x=point.x, y=point.y))
        except Exception:  # pylint: disable=broad-exception-caught
            # Navigation, dialogs and detached sessions must not fail the input itself.
            return None
        return CursorStyle.parse(style)

    def invalidate_frames(self) -> None:
        """Forget cached frame geometry after input, scrolling or navigation moved content."""
        self._layout_revision += 1

    async def frames(self) -> tuple[Frame, ...]:
        """Return every frame with its viewport transform; `frame_limitations` explains gaps.

        One discovery is reused within an action until input or navigation invalidates it.
        """
        if self._discover_frames is None:
            raise BrowserError("Frame discovery is unavailable for this tab")
        key = (self.document_id, self.input.action_id, self._layout_revision)
        if key[1] and key == self._frames_key:
            return self._frames
        frames, self.frame_limitations = await self._discover_frames(self)
        if key[1] and key == (self.document_id, self.input.action_id, self._layout_revision):
            self._frames_key, self._frames = key, frames
        return frames

    async def handle(self, event: object) -> None:
        """Apply a page event that arrived on this tab's own CDP session."""
        match event:
            case FrameNavigatedEvent(frame=frame) if not frame.parent_id:
                self.document_id, self.url = frame.loader_id, frame.url
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
            case NavigatedWithinDocumentEvent(url=url):
                self.url = url
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
            case JavascriptDialogOpeningEvent(type=kind, message=message):
                self.dialog = (str(kind), message)
                await self.emit(DialogOpenedEvent(kind=str(kind), message=message[:1000]))
            case JavascriptDialogClosedEvent(result=accepted):
                self.dialog = None
                await self.emit(DialogHandledEvent(accepted=accepted))

    async def main_frame(self) -> Frame:
        tree = await self.frame_tree()
        return Frame(tree.frame.id, self.cdp, document_id=tree.frame.loader_id, worlds=self.worlds)

    async def frame_tree(self) -> FrameTree:
        return await _frame_tree(self.cdp)

    async def sync_document(self) -> None:
        tree = await self.frame_tree()
        if self.document_id != tree.frame.loader_id:
            self.worlds.invalidate(frame_id=tree.frame.id)
            self.invalidate_frames()
        self.document_id, self.url = tree.frame.loader_id, tree.frame.url

    async def go_back(self) -> bool:
        return await self._history(-1)

    async def go_forward(self) -> bool:
        return await self._history(1)

    async def can_go_forward(self) -> bool:
        history = await self.cdp.page.get_navigation_history()
        return history.current_index + 1 < len(history.entries)

    async def reload(self) -> None:
        await self.cdp.page.reload()

    async def evaluate(self, expression: str, *, timeout: float = 10) -> str:
        """Evaluate once in the main page world and render its completion value."""
        group = f"browserrig-evaluate-{uuid4().hex}"
        try:
            async with asyncio.timeout(timeout):
                result = await self.cdp.runtime.evaluate(
                    expression=expression,
                    object_group=group,
                    return_by_value=True,
                    await_promise=True,
                    repl_mode=True,
                    user_gesture=True,
                    timeout=timeout * 1000,
                )
            if details := result.exception_details:
                message = (
                    _javascript_value(details.exception)
                    if details.exception is not None
                    else details.text
                )
                raise BrowserError(f"JavaScript failed: {message}")
            return _javascript_value(result.result)
        except TimeoutError as error:
            raise BrowserError(f"JavaScript timed out after {timeout:g} seconds") from error
        except CDPCommandError as error:
            if error.message == "Object couldn't be returned by value":
                raise BrowserError(
                    "JavaScript executed, but its result cannot be returned by value; "
                    "return JSON-serializable data"
                ) from error
            raise
        finally:
            self.invalidate_frames()
            with suppress(CDPCommandError):
                await self.cdp.runtime.release_object_group(object_group=group)

    async def handle_dialog(self, *, accept: bool, text: str = "") -> None:
        await self.cdp.page.handle_java_script_dialog(accept=accept, prompt_text=text)

    async def bring_to_front(self) -> None:
        await self.cdp.page.bring_to_front()

    async def navigate(self, url: str) -> None:
        result = await self.cdp.page.navigate(url=validated_url(url))
        if result.error_text:
            raise BrowserError(f"Navigation failed: {result.error_text}")

    async def _history(self, offset: int) -> bool:
        history = await self.cdp.page.get_navigation_history()
        index = history.current_index + offset
        if not 0 <= index < len(history.entries):
            return False
        await self.cdp.page.navigate_to_history_entry(entry_id=history.entries[index].id)
        return True


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or (parsed.scheme in {"http", "https"} and parsed.hostname):
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


async def _frame_tree(cdp: CdpSession) -> FrameTree:
    result = await cdp.page.get_frame_tree()
    return result.frame_tree


def _javascript_value(value: RemoteObject) -> str:
    if value.unserializable_value is not None:
        return value.unserializable_value
    if value.type == "undefined":
        return "undefined"
    if value.value is None and value.subtype != "null" and value.description is not None:
        return value.description
    return json.dumps(value.value, ensure_ascii=False)


async def _call_on_node[A: BaseModel, R](
    cdp: CdpSession,
    backend_node_id: int,
    script: Script[A, R],
    args: A | None,
    context: int,
    *,
    by_value: bool,
    user_gesture: bool,
) -> Any:
    try:
        resolved = await cdp.dom.resolve_node(
            backend_node_id=backend_node_id, execution_context_id=context
        )
    except CDPCommandError as error:
        raise BrowserError("STALE_ELEMENT") from error
    object_id = resolved.object.object_id
    if object_id is None:
        raise BrowserError("STALE_ELEMENT")
    try:
        return await _call(
            cdp, script, args, object_id=object_id, by_value=by_value, user_gesture=user_gesture
        )
    finally:
        with suppress(CDPCommandError):
            await cdp.runtime.release_object(object_id=object_id)


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
