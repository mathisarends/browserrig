import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from dataclasses import replace
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from cdpify import CdpSession
from cdpify.domains.input import MouseButton
from cdpify.domains.page import (
    FrameNavigatedEvent,
    FrameStartedLoadingEvent,
    FrameStartedNavigatingEvent,
    FrameStoppedLoadingEvent,
    FrameTree,
    JavascriptDialogClosedEvent,
    JavascriptDialogOpeningEvent,
    LifecycleEventEvent,
    NavigatedWithinDocumentEvent,
)
from cdpify.domains.runtime import RemoteObject
from cdpify.exceptions import CDPCommandError

from browserrig.core import (
    BrowserError,
    CursorStyle,
    MouseEventKind,
    Point,
)
from browserrig.events import (
    BrowserEvent,
    DialogHandledEvent,
    DialogOpenedEvent,
    LiveEvent,
    NavigationCommittedEvent,
    TabUpdatedEvent,
)
from browserrig.input import KeyEventType
from browserrig.scripts import (
    CURSOR,
    TAB_STRIP,
    CursorArgs,
)

from .favicon import load_favicon
from .frame import Frame
from .worlds import Worlds

# A cursor shape is presentation only and must never hold up input.
_CURSOR_PROBE_SECONDS = 0.25
_STRIP_SECONDS = 10


type FrameDiscovery = Callable[
    [Tab], Awaitable[tuple[tuple[Frame, ...], tuple[str, ...]]]
]


class Tab:  # pylint: disable=too-many-public-methods  # document API plus InputTarget
    def __init__(
        self,
        target_id: str,
        cdp: CdpSession,
        *,
        emit: Callable[[BrowserEvent | LiveEvent], Awaitable[None]] | None = None,
        worlds: Worlds | None = None,
        discover_frames: FrameDiscovery | None = None,
        current_action: Callable[[], str] = lambda: "",
    ) -> None:
        self.id = target_id
        self.cdp = cdp
        self.document_id = ""
        self.url = "about:blank"
        self.title = ""
        self.dialog: tuple[str, str] | None = None
        self._dialog_opened = asyncio.Event()
        self.closed = False
        # Tab-strip state for live viewers; see `TabUpdatedEvent`.
        self.loading = False  # smelt: ignore[SMT430] -- public Tab state like url/title
        self.navigation_pending = False
        self._navigation_loader = ""
        self._navigation_document = ""
        self.favicon = ""
        self._main_frame_id = target_id
        self._icon_url = ""
        self._strip_task: asyncio.Task[None] | None = None
        self._shown: tuple[str, str, bool, str] | None = None
        self.changed = asyncio.Event()
        self.frame_limitations: tuple[str, ...] = ()
        self.worlds = worlds if worlds is not None else Worlds()
        self._emit = emit
        self._discover_frames = discover_frames
        self._layout_revision = 0
        self._frames_key: tuple[str, str, int] | None = None
        self._frames: tuple[Frame, ...] = ()
        self._current_action = current_action

    async def emit(self, event: BrowserEvent | LiveEvent) -> None:
        if self._emit is not None:
            await self._emit(
                replace(event, target_id=self.id, document_id=self.document_id)
            )

    async def publish_state(self) -> None:
        """Tell live viewers what the tab strip shows, once per distinct state."""
        state = (self.url, self.title, self.loading, self.favicon)
        if self._emit is None or self.closed or state == self._shown:
            return
        self._shown = state
        await self.emit(
            TabUpdatedEvent(
                url=self.url,
                title=self.title,
                loading=self.loading,
                favicon=self.favicon,
            )
        )

    def refresh_strip(self) -> None:
        """Read title and icon in the background; a slow icon host never holds up events."""
        if self._emit is None or self.closed:
            return
        if self._strip_task is not None:
            self._strip_task.cancel()
        self._strip_task = asyncio.create_task(
            self._load_strip(), name=f"browserrig:tab-strip:{self.id}"
        )

    def discard(self) -> None:
        self.closed = True
        if self._strip_task is not None:
            self._strip_task.cancel()
            self._strip_task = None

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

    def layout_changed(self) -> None:
        """Forget cached frame geometry after input, scrolling or navigation moved content."""
        self._layout_revision += 1

    # Native input lands here; the browser's mouse and keyboard aim at the focused tab.
    async def dispatch_mouse(
        self,
        kind: Literal[
            MouseEventKind.MOVED, MouseEventKind.PRESSED, MouseEventKind.RELEASED
        ],
        point: Point,
        *,
        button: MouseButton,
        buttons: int,
        click_count: int,
    ) -> None:
        await self._input(
            self.cdp.input.dispatch_mouse_event(
                type=kind.value,
                x=point.x,
                y=point.y,
                button=button,
                buttons=buttons,
                click_count=click_count,
            )
        )

    async def dispatch_wheel(
        self, point: Point, *, delta_x: float, delta_y: float
    ) -> None:
        await self._input(
            self.cdp.input.dispatch_mouse_event(
                type=MouseEventKind.WHEEL.value,  # smelt: ignore[SMT318] -- cdpify wants a Literal
                x=point.x,
                y=point.y,
                delta_x=delta_x,
                delta_y=delta_y,
            )
        )

    async def dispatch_key(
        self,
        kind: KeyEventType,
        *,
        modifiers: int,
        key: str,
        code: str,
        windows_virtual_key_code: int,
        text: str | None = None,
    ) -> None:
        await self._input(
            self.cdp.input.dispatch_key_event(
                type=kind,
                modifiers=modifiers,
                key=key,
                code=code,
                windows_virtual_key_code=windows_virtual_key_code,
                text=text,
            )
        )

    async def cancel_drag(self) -> None:
        await self.cdp.input.cancel_dragging()

    async def viewport_size(self) -> tuple[float, float]:
        viewport = (await self.cdp.page.get_layout_metrics()).css_layout_viewport
        return viewport.client_width, viewport.client_height

    async def frames(self) -> tuple[Frame, ...]:
        """Return every frame with its viewport transform; `frame_limitations` explains gaps.

        One discovery is reused within an action until input or navigation invalidates it.
        """
        if self._discover_frames is None:
            raise BrowserError("Frame discovery is unavailable for this tab")
        key = (self.document_id, self._current_action(), self._layout_revision)
        if key[1] and key == self._frames_key:
            return self._frames
        frames, self.frame_limitations = await self._discover_frames(self)
        if key[1] and key == (
            self.document_id,
            self._current_action(),
            self._layout_revision,
        ):
            self._frames_key = key
            self._frames = frames
        return frames

    async def handle(self, event: object) -> None:
        """Apply a page event that arrived on this tab's own CDP session."""
        match event:
            case FrameNavigatedEvent(frame=frame) if not frame.parent_id:
                self.document_id = frame.loader_id
                self.url = frame.url
                self._main_frame_id = frame.id
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
                await self.publish_state()
            case NavigatedWithinDocumentEvent(url=url, frame_id=frame_id) if (
                frame_id == self._main_frame_id
            ):
                self.navigation_pending = False
                self.url = url
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
                await self.publish_state()
            case FrameStartedNavigatingEvent(frame_id=frame_id, loader_id=loader) if (
                frame_id == self._main_frame_id
            ):
                self.navigation_pending = True
                self._navigation_loader = loader
                self._navigation_document = self.document_id
            case FrameStartedLoadingEvent(frame_id=frame_id) if (
                frame_id == self._main_frame_id
            ):
                self.loading = True
                if not self.navigation_pending:
                    self._navigation_loader = ""
                    self._navigation_document = self.document_id
                self.navigation_pending = True
                await self.publish_state()
            case LifecycleEventEvent(
                frame_id=frame_id, loader_id=loader, name="DOMContentLoaded"
            ) if frame_id == self._main_frame_id:
                if loader == self._navigation_loader or (
                    loader == self.document_id
                    and self.document_id != self._navigation_document
                ):
                    self.navigation_pending = False
            case FrameStoppedLoadingEvent(frame_id=frame_id) if (
                frame_id == self._main_frame_id
            ):
                self.loading = False
                self.navigation_pending = False
                await self.publish_state()
                self.refresh_strip()
            case JavascriptDialogOpeningEvent(type=kind, message=message):
                self.dialog = (str(kind), message)
                self._dialog_opened.set()
                await self.emit(
                    DialogOpenedEvent(kind=str(kind), message=message[:1000])
                )
            case JavascriptDialogClosedEvent(result=accepted):
                self.dialog = None
                self._dialog_opened.clear()
                await self.emit(DialogHandledEvent(accepted=accepted))

    async def main_frame(self) -> Frame:
        tree = await self.frame_tree()
        return Frame(
            tree.frame.id,
            self.cdp,
            document_id=tree.frame.loader_id,
            worlds=self.worlds,
        )

    async def frame_tree(self) -> FrameTree:
        result = await self.cdp.page.get_frame_tree()
        return result.frame_tree

    async def sync_document(self) -> None:
        if self.dialog is not None:
            # The page answers nothing while a dialog blocks it, and cannot navigate either.
            return
        tree = await self.frame_tree()
        if self.document_id != tree.frame.loader_id:
            self.worlds.invalidate(frame_id=tree.frame.id)
            self.layout_changed()
        self.document_id = tree.frame.loader_id
        self.url = tree.frame.url
        self._main_frame_id = tree.frame.id

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
            raise BrowserError(
                f"JavaScript timed out after {timeout:g} seconds"
            ) from error
        except CDPCommandError as error:
            if error.message == "Object couldn't be returned by value":
                raise BrowserError(
                    "JavaScript executed, but its result cannot be returned by value; "
                    "return JSON-serializable data"
                ) from error
            raise
        finally:
            self.layout_changed()
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

    async def _load_strip(self) -> None:
        try:
            async with asyncio.timeout(_STRIP_SECONDS):
                if self.dialog is None:
                    frame = await self.main_frame()
                    strip = await frame.run(TAB_STRIP)
                    # Chrome's target info often keeps the host as title; the document knows.
                    self.title = strip.title or self.title
                    if strip.icon != self._icon_url:
                        await self.publish_state()
                        self._icon_url = strip.icon
                        self.favicon = (
                            await load_favicon(self.cdp, frame.id, strip.icon)
                            if strip.icon
                            else ""
                        )
                await self.publish_state()
        except Exception:  # pylint: disable=broad-exception-caught
            # Navigation, dialogs and detached sessions only cost the strip state, never the tab.
            return

    async def _input(self, command: Coroutine[Any, Any, None]) -> None:
        """Send input, returning early when it opens a JavaScript dialog.

        Chrome answers an input event only after its handlers finish, and an alert, confirm
        or prompt holds them until the dialog closes. The input has landed by then, so the
        reply is left to arrive later.
        """
        if self.dialog is not None:
            await command
            return
        # Started eagerly, input that needs no reply lands within the caller's step.
        sent = asyncio.Task(command, loop=asyncio.get_running_loop(), eager_start=True)
        if not sent.done():
            opened = asyncio.ensure_future(self._dialog_opened.wait())
            try:
                await asyncio.wait((sent, opened), return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                sent.cancel()
                raise
            finally:
                opened.cancel()
        if not sent.done():
            sent.add_done_callback(_discard_result)
            return
        sent.result()

    async def _history(self, offset: int) -> bool:
        history = await self.cdp.page.get_navigation_history()
        index = history.current_index + offset
        if not 0 <= index < len(history.entries):
            return False
        await self.cdp.page.navigate_to_history_entry(
            entry_id=history.entries[index].id
        )
        return True


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or (parsed.scheme in {"http", "https"} and parsed.hostname):
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


def _discard_result(task: asyncio.Future[None]) -> None:
    # The reply of input that opened a dialog only reports when the dialog closed.
    if not task.cancelled():
        task.exception()


def _javascript_value(value: RemoteObject) -> str:
    if value.unserializable_value is not None:
        return value.unserializable_value
    if value.type == "undefined":
        return "undefined"
    if (
        value.value is None
        and value.subtype != "null"
        and value.description is not None
    ):
        return value.description
    return json.dumps(value.value, ensure_ascii=False)
