import asyncio
import logging
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field

from harnessed import Plugin
from harnessed.kernel import PluginScope, PluginState, hook, needs

from browserrig.browser import Browser, TabChanged
from browserrig.choreography import (
    ActivityPresentedEvent,
    Choreography,
    PresentedEvent,
)
from browserrig.core import BrowserError
from browserrig.events import InputEvent, PointerReleasedEvent

from .view import KeyboardLayout, OverlayStyle, OverlayView, Theme

logger = logging.getLogger(__name__)
# A document that does not answer in time costs the overlay, never the step.
_SHOW_SECONDS = 2.5


@dataclass
class _Overlay:
    """One session's view and the activity receipts still waiting to be shown."""

    view: OverlayView | None = None
    activities: deque[ActivityPresentedEvent] = field(default_factory=deque)
    activity_task: asyncio.Task[None] | None = None


class ChoreographyOverlay(
    Plugin, slot="browserrig.choreography-overlay", needs=(Choreography,)
):
    """Draw the session's choreography inside the active tab for people watching it.

    A transparent, inert iframe shows cursor, keyboard, browser UI and presented
    receipts; live viewers and native recordings see it, model screenshots do not. It
    only consumes what `Choreography` emits and never reads browser facts itself.
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
        scope.on(InputEvent, self._show)
        scope.on(PresentedEvent, self._presented)
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

    async def _presented(self, event: PresentedEvent) -> None:
        if not isinstance(event, ActivityPresentedEvent):
            await self._show(event)
            return
        # Status rendering must never hold up model/control hooks.
        state = self._state
        state.activities.append(event)
        if state.activity_task is None:
            state.activity_task = asyncio.create_task(self._show_activities())

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

    async def _show(self, event: InputEvent | PresentedEvent) -> None:
        view = self._state.view
        # The overlay animates a click on press. An unused release can block on a tab
        # that Chrome already moved to the background.
        if view is None or isinstance(event, PointerReleasedEvent):
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
