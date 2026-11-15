import asyncio
import logging
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field

from harnessed import Plugin, PluginState, hook
from harnessed.kernel import PluginScope, needs

from browserrig.browser import Browser, TabChanged
from browserrig.choreography import WorkPresentedEvent
from browserrig.core import BrowserError
from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    BrowserEvent,
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
    InputEvent,
    LiveEvent,
)

from .view import KeyboardLayout, OverlayStyle, OverlayView, Theme

logger = logging.getLogger(__name__)
# A document that does not answer in time costs the overlay, never the step.
_SHOW_SECONDS = 2.5


@dataclass
class _Overlay:
    """One session's view and the status events still waiting to be shown."""

    view: OverlayView | None = None
    activities: deque[BrowserEvent] = field(default_factory=deque)
    activity_task: asyncio.Task[None] | None = None


class ChoreographyOverlay(Plugin, slot="browserrig.choreography-overlay"):
    """Draw the session's choreography inside the active tab for people watching it.

    A transparent, inert iframe shows cursor, keyboard, browser UI and work receipts;
    live viewers and native recordings see it, model screenshots do not. It only
    consumes events: input appears with `Choreography`, activity and downloads without.
    """

    _state = PluginState(_Overlay)
    _browser = needs(Browser)

    def __init__(
        self,
        *,
        name: str = "Browserrig",
        keyboard_layout: KeyboardLayout = "en",
        theme: Theme = "dark",
    ) -> None:
        super().__init__()
        self.style = OverlayStyle(
            name=name, keyboard_layout=keyboard_layout, theme=theme
        )

    async def setup(self, scope: PluginScope) -> None:
        view = self._state.view = OverlayView(self.style)
        scope.effect(view.close)
        scope.on(LiveEvent, self._live_event)
        scope.on(BrowserEvent, self._browser_event)
        scope.effect(self._stop_activities)

    @hook(TabChanged)
    async def _restore(self, event: TabChanged) -> None:
        view = self._state.view
        if view is None or not event.settled or event.tab.closed:
            return
        if event.tab.id != self._browser.active_tab.id:
            return
        try:
            async with asyncio.timeout(_SHOW_SECONDS):
                await view.restore(event.tab)
        except (BrowserError, TimeoutError):
            logger.debug("Overlay restoration unavailable")

    async def _live_event(self, event: LiveEvent) -> None:
        if isinstance(event, (InputEvent, DownloadProgressedEvent, WorkPresentedEvent)):
            await self._show(event)

    async def _browser_event(self, event: BrowserEvent) -> None:
        if isinstance(event, (ActivityStartedEvent, ActivityFinishedEvent)):
            # Status rendering must never hold up model/control hooks.
            state = self._state
            state.activities.append(event)
            if state.activity_task is None:
                state.activity_task = asyncio.create_task(self._show_activities())
        elif isinstance(
            event,
            (
                DownloadStartedEvent,
                DownloadCompletedEvent,
                DownloadFailedEvent,
                DownloadCanceledEvent,
                FilesUploadedEvent,
            ),
        ):
            await self._show(event)

    async def _show_activities(self) -> None:
        state = self._state
        try:
            while state.activities:
                await self._show(state.activities.popleft())
        finally:
            state.activity_task = None

    async def _stop_activities(self) -> None:
        state = self._state
        task = state.activity_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        state.activities.clear()

    async def _show(self, event: LiveEvent | BrowserEvent) -> None:
        view = self._state.view
        if view is None:
            return
        view.remember(event)
        try:
            tab = self._browser.active_tab
            if (
                isinstance(event, InputEvent)
                and event.target_id
                and tab.id != event.target_id
            ):
                return
            if tab.closed or tab.navigation_pending or tab.dialog is not None:
                view.suspend()
                return
            async with asyncio.timeout(_SHOW_SECONDS):
                await view.show(tab, event)
        except (BrowserError, TimeoutError):
            view.suspend()
            # Presentation cannot turn successful native input into failed input.
            logger.debug("Choreography overlay unavailable for the current document")
