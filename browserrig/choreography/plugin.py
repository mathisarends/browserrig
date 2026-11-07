import asyncio
import logging
from collections import deque
from contextlib import suppress
from typing import Any

from harnessed import Plugin, hook
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


class InputVisualization(Plugin, slot="browserrig.choreography"):
    """Stage the browser for people watching: visible input and browser UI.

    Tools and input devices only describe what they do. This plugin streams input as
    live events, shows browser UI such as the address and find bars and highlights the
    elements tools act on. How fast input runs is up to `InputPacing`. Without this plugin
    no input events are emitted.
    """

    events = INPUT_EVENTS + SCENE_EVENTS
    _browser = needs(Browser)

    def __init__(self, *, renderer: IframeRenderer | None = _DEFAULT_RENDERER) -> None:
        super().__init__()
        self.renderer = renderer
        self._view: IframeView | None = None
        self._activities: deque[BrowserEvent] = deque()
        self._activity_task: asyncio.Task[None] | None = None

    async def setup(self, ctx: Scope) -> None:
        inputs = self._browser.input
        ctx.effect(inputs.present(Stage(lambda: inputs.action_id)))
        if self.renderer is not None:
            self._view = self.renderer.create()
            ctx.effect(self._view.close)
            ctx.on(LiveEvent, self._render)
            ctx.on(BrowserEvent, self._browser_event)
            ctx.effect(self._stop_activities)

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach late, so seed their cursor at turn start.
            await inputs.mouse.publish_cursor()

        ctx.on(TurnStartedEvent, publish_cursor)

    @hook(TabChanged)
    async def _refresh(self, event: TabChanged) -> None:
        if not event.settled or event.tab.closed or self._view is None:
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
                self._activities.append(event)
                if self._activity_task is None:
                    self._activity_task = asyncio.create_task(self._show_activities())
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
        try:
            while self._activities:
                await self._present(self._activities.popleft())
        finally:
            self._activity_task = None

    async def _stop_activities(self) -> None:
        task = self._activity_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._activities.clear()

    async def _present(self, event: LiveEvent | BrowserEvent) -> None:
        if self._view is None:
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
                await self._view.show(tab, event)
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
