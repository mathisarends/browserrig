import asyncio
import logging
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from harnessed import Plugin, PluginState, hook
from harnessed.events import TurnStartedEvent
from harnessed.hooks import Next
from harnessed.kernel import Scope, needs

from browserrig.browser import Browser, TabChanged
from browserrig.core import ActivityKind, BrowserError
from browserrig.events import (
    INPUT_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    BrowserEvent,
    CursorStateEvent,
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
    InputEvent,
    LiveEvent,
)
from browserrig.tools import (
    FindIntent,
    NavigateIntent,
    OpenFileIntent,
    Perform,
    TargetLocated,
    UploadIntent,
    WaitIntent,
)

from . import scenes
from .events import SCENE_EVENTS, HighlightElementEvent
from .renderer import IframeRenderer, IframeView
from .stage import Stage

logger = logging.getLogger(__name__)
_DEFAULT_RENDERER = IframeRenderer()


@dataclass
class _Presentation:
    """One session's view and the status events still waiting to be shown."""

    view: IframeView | None = None
    activities: deque[BrowserEvent] = field(default_factory=deque)
    activity_task: asyncio.Task[None] | None = None


class InputVisualization(Plugin, slot="browserrig.choreography"):
    """Stage the browser for people watching: visible input and browser UI.

    Tools and input devices only describe what they do. This plugin streams input as
    live events, shows browser UI such as the address and find bars and highlights the
    elements tools act on. How fast input runs is up to `InputPacing`. Without this plugin
    no input events are emitted.
    """

    events = INPUT_EVENTS + SCENE_EVENTS
    _state = PluginState(_Presentation)
    _browser = needs(Browser)

    def __init__(self, *, renderer: IframeRenderer | None = _DEFAULT_RENDERER) -> None:
        super().__init__()
        self.renderer = renderer

    async def setup(self, ctx: Scope) -> None:
        # Each call installs now and registers its undo for teardown.
        ctx.effect(self._browser.input.present(Stage()))
        if self.renderer is not None:
            view = self._state.view = self.renderer.create()
            ctx.effect(view.close)
            ctx.on(LiveEvent, self._render)
            ctx.on(BrowserEvent, self._browser_event)
            ctx.effect(self._stop_activities)

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach late, so seed their cursor at turn start.
            await self._browser.mouse.publish_cursor()

        ctx.on(TurnStartedEvent, publish_cursor)

    @hook(TabChanged)
    async def _refresh(self, event: TabChanged) -> None:
        if not event.settled or event.tab.closed or self._state.view is None:
            return
        if event.tab.id != self._browser.active_tab.id:
            return
        point = self._browser.mouse.position_in(event.tab.id)
        if point is not None:
            await self._render(
                CursorStateEvent(x=point.x, y=point.y, target_id=event.tab.id)
            )

    async def _render(self, event: LiveEvent) -> None:
        if isinstance(event, (InputEvent, DownloadProgressedEvent)):
            await self._present(event)

    async def _browser_event(self, event: BrowserEvent) -> None:
        if isinstance(event, (ActivityStartedEvent, ActivityFinishedEvent)):
            if event.kind in {
                ActivityKind.LLM,
                ActivityKind.COMPACTION,
                ActivityKind.PAUSED,
            }:
                # Status rendering must never hold up model/control hooks.
                state = self._state
                state.activities.append(event)
                if state.activity_task is None:
                    state.activity_task = asyncio.create_task(self._show_activities())
            return
        if isinstance(
            event,
            (
                DownloadStartedEvent,
                DownloadCompletedEvent,
                DownloadFailedEvent,
                DownloadCanceledEvent,
                FilesUploadedEvent,
            ),
        ):
            await self._present(event)

    async def _show_activities(self) -> None:
        state = self._state
        try:
            while state.activities:
                await self._present(state.activities.popleft())
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

    async def _present(self, event: LiveEvent | BrowserEvent) -> None:
        view = self._state.view
        if view is None:
            return
        try:
            tab = self._browser.active_tab
            if (
                (event.target_id and tab.id != event.target_id)
                or tab.closed
                or tab.navigation_pending
                or tab.dialog is not None
            ):
                return
            async with asyncio.timeout(2.5):
                await view.show(tab, event)
        except (BrowserError, TimeoutError):
            # Presentation cannot turn successful native input into failed input.
            logger.debug("Input presentation unavailable for the current document")

    @hook(Perform)
    async def _stage(self, event: Perform, next_: Next[Any]) -> Any:
        scene = scenes.Scene(event.tab, event.action_id)
        match event.intent:
            case FindIntent() as intent:
                return await scenes.find(scene, intent, next_)
            case NavigateIntent() as intent:
                return await scenes.navigate(scene, intent, next_)
            case WaitIntent() as intent:
                return await scenes.wait(scene, intent, next_)
            case OpenFileIntent() as intent:
                return await scenes.open_file(scene, intent, next_)
            case UploadIntent() as intent:
                return await scenes.upload(scene, intent, next_)
        return await next_()

    @hook(TargetLocated)
    async def _highlight(self, event: TargetLocated) -> None:
        bounds = event.bounds
        await event.tab.emit(
            HighlightElementEvent(
                ref=event.ref,
                x=bounds.x,
                y=bounds.y,
                width=bounds.width,
                height=bounds.height,
                action_id=event.action_id,
            )
        )
