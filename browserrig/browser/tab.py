import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import uuid4

from cdpify import UNSET, CDPCommandError, CdpSession
from cdpify.domains.page import (
    FrameNavigatedEvent,
    FrameResizedEvent,
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
from harnessed.tracing import record, traced

from browserrig.core import BrowserError
from browserrig.events import (
    BrowserEvent,
    DialogHandledEvent,
    DialogOpenedEvent,
    LiveEvent,
    NavigationCommittedEvent,
)
from browserrig.scripts import (
    TAB_STRIP,
    TabStrip,
)

from .favicon import load_favicon
from .frame import Frame
from .guard import NavigationGuard
from .input import CdpInput
from .network import NetworkActivity
from .overlays import Overlays
from .worlds import Worlds

type FrameDiscovery = Callable[
    [Tab], Awaitable[tuple[tuple[Frame, ...], tuple[str, ...]]]
]
# Told when url, title or loading may have changed; `settled` once loading stopped.
type TabListener = Callable[[Tab, bool], Awaitable[None]]


class Tab:  # pylint: disable=too-many-public-methods  # document API
    def __init__(
        self,
        target_id: str,
        cdp: CdpSession,
        *,
        emit: Callable[[BrowserEvent | LiveEvent], Awaitable[None]] | None = None,
        worlds: Worlds | None = None,
        discover_frames: FrameDiscovery | None = None,
        current_action: Callable[[], str] = lambda: "",
        on_change: TabListener | None = None,
        guard: NavigationGuard | None = None,
    ) -> None:
        self.id = target_id
        self.cdp = cdp
        self.document_id = ""
        self.url = "about:blank"
        self.title = ""
        self.dialog: tuple[str, str] | None = None
        self.input = CdpInput(self)
        self.overlays = Overlays(self)
        self.network = NetworkActivity()
        self.closed = False
        self.loading = False
        self.navigation_pending = False
        self._navigation_loader = ""
        self._navigation_document = ""
        self._main_frame_id = target_id
        self.changed = asyncio.Event()
        self.frame_limitations: tuple[str, ...] = ()
        self.worlds = worlds if worlds is not None else Worlds()
        self._emit = emit
        self._discover_frames = discover_frames
        self._layout_revision = 0
        # Counts viewport resizes, as when a person resizes the browser window.
        self.viewport_revision = 0
        self._frames_key: tuple[str, str, int] | None = None
        self._frames: tuple[Frame, ...] = ()
        self._current_action = current_action
        self._on_change = on_change
        self._guard = guard

    async def handle(self, event: object) -> None:
        """Apply a page event that arrived on this tab's own CDP session."""
        self.network.handle(event)
        match event:
            case FrameNavigatedEvent(frame=frame) if not frame.parent_id:
                self.document_id = frame.loader_id
                self.url = frame.url
                self._main_frame_id = frame.id
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
                await self.report_change()
            case NavigatedWithinDocumentEvent(url=url, frame_id=frame_id) if (
                frame_id == self._main_frame_id
            ):
                self.navigation_pending = False
                self.url = url
                self.changed.set()
                await self.emit(NavigationCommittedEvent(url=self.url))
                await self.report_change()
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
                await self.report_change()
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
                await self.report_change(settled=True)
            case FrameResizedEvent():
                self.viewport_revision += 1
                self.layout_changed()
            case JavascriptDialogOpeningEvent(type=kind, message=message):
                self.dialog = (str(kind), message)
                self.input.dialog_opened.set()
                await self.emit(
                    DialogOpenedEvent(kind=str(kind), message=message[:1000])
                )
            case JavascriptDialogClosedEvent(result=accepted):
                self.dialog = None
                self.input.dialog_opened.clear()
                await self.emit(DialogHandledEvent(accepted=accepted))

    async def emit(self, event: BrowserEvent | LiveEvent) -> None:
        if self._emit is not None:
            await self._emit(
                replace(event, target_id=self.id, document_id=self.document_id)
            )

    async def discard(self) -> None:
        self.closed = True
        await self.report_change()

    async def report_change(self, *, settled: bool = False) -> None:
        """Tell the change listener that url, title or loading may have changed."""
        if self._on_change is not None:
            await self._on_change(self, settled)

    async def read_strip(self) -> TabStrip:
        """Read the title and icon URL the document declares for a tab strip."""
        frame = await self.main_frame()
        return await frame.run(TAB_STRIP)

    async def load_icon(self, url: str) -> str:
        """Load an icon through the page's own network stack, as a `data:` URI."""
        return await load_favicon(self.cdp, self._main_frame_id, url)

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

    @traced
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

    def layout_changed(self) -> None:
        """Forget cached frame geometry after input, scrolling or navigation moved content."""
        self._layout_revision += 1

    async def viewport_size(self) -> tuple[float, float]:
        viewport = (await self.cdp.page.get_layout_metrics()).css_layout_viewport
        return viewport.client_width, viewport.client_height

    @traced
    async def frames(self) -> tuple[Frame, ...]:
        """Return every frame with its viewport transform; `frame_limitations` explains gaps.

        One discovery is reused within an action until input or navigation invalidates it.
        """
        if self._discover_frames is None:
            raise BrowserError("Frame discovery is unavailable for this tab")
        key = (self.document_id, self._current_action(), self._layout_revision)
        cached = bool(key[1]) and key == self._frames_key
        record(cached=cached)
        if cached:
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

    async def go_back(self) -> bool:
        return await self._history(-1)

    async def go_forward(self) -> bool:
        return await self._history(1)

    async def can_go_back(self) -> bool:
        history = await self.cdp.page.get_navigation_history()
        return history.current_index > 0

    async def can_go_forward(self) -> bool:
        history = await self.cdp.page.get_navigation_history()
        return history.current_index + 1 < len(history.entries)

    @traced
    async def reload(self) -> None:
        await self.cdp.page.reload()

    async def handle_dialog(self, *, accept: bool, text: str = "") -> None:
        await self.cdp.page.handle_java_script_dialog(accept=accept, prompt_text=text)

    async def bring_to_front(self) -> None:
        await self.cdp.page.bring_to_front()

    @traced
    async def navigate(self, url: str) -> None:
        if self._guard is not None:
            await self._guard.check(url, self.id)
        result = await self.cdp.page.navigate(url=validated_url(url))
        self.check_navigation()
        if result.error_text:
            raise BrowserError(f"Navigation failed: {result.error_text}")

    def check_navigation(self) -> None:
        """Report an intercepted navigation once, before an action reports success."""
        if self._guard is not None:
            self._guard.raise_if_blocked(self.id)

    async def _history(self, offset: int) -> bool:
        history = await self.cdp.page.get_navigation_history()
        index = history.current_index + offset
        if not 0 <= index < len(history.entries):
            return False
        if self._guard is not None:
            await self._guard.check(history.entries[index].url, self.id)
        await self.cdp.page.navigate_to_history_entry(
            entry_id=history.entries[index].id
        )
        return True


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or (parsed.scheme in {"http", "https"} and parsed.hostname):
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


def _javascript_value(value: RemoteObject) -> str:
    if value.unserializable_value is not None:
        return value.unserializable_value
    if value.type == "undefined":
        return "undefined"
    if value.value is UNSET:
        return value.description if value.description is not None else "null"
    return json.dumps(value.value, ensure_ascii=False)
