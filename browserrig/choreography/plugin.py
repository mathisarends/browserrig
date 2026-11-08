import asyncio
import logging
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any

from harnessed import Plugin, PluginState, ToolResult, ToolStatus, hook
from harnessed.events import ToolCallFinishedEvent, TurnEndedEvent, TurnStartedEvent
from harnessed.hooks import ExecuteTool, Next
from harnessed.kernel import PluginScope, needs

from browserrig.browser import Browser, BrowserEvents, TabChanged
from browserrig.core import ActionKind, BrowserError, BrowserToolMetadata
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
    ObservationCapturedEvent,
)
from browserrig.observation import BrowserPerception
from browserrig.secrets import Secrets
from browserrig.tools import (
    FindIntent,
    NavigateIntent,
    OpenFileIntent,
    Perform,
    TargetLocated,
    UploadIntent,
    WaitIntent,
)

from . import scenes, work
from .events import (
    SCENE_EVENTS,
    CaptureRegion,
    HighlightElementEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from .images import thumbnail
from .projection import project
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
    context: PluginScope | None = None
    screenshot: WorkPresentedEvent | None = None
    running: dict[str, WorkPresentedEvent] = field(default_factory=dict)
    handled: set[str] = field(default_factory=set)


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
    _events = needs(BrowserEvents)

    def __init__(self, *, renderer: IframeRenderer | None = _DEFAULT_RENDERER) -> None:
        super().__init__()
        self.renderer = renderer

    async def setup(self, scope: PluginScope) -> None:
        self._state.context = scope
        scope.on(BrowserEvent, self._browser_event)
        # Each call installs now and registers its undo for teardown.
        scope.effect(self._browser.input.present(Stage()))
        if self.renderer is not None:
            view = self._state.view = self.renderer.create()
            scope.effect(view.close)
            scope.on(LiveEvent, self._render)
            scope.effect(self._stop_activities)

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach late, so seed their cursor at turn start.
            await self._browser.input.mouse.publish_cursor()

        scope.on(TurnStartedEvent, publish_cursor)

    @hook(TabChanged)
    async def _refresh(self, event: TabChanged) -> None:
        if not event.settled or event.tab.closed or self._state.view is None:
            return
        if event.tab.id != self._browser.active_tab.id:
            return
        point = self._browser.input.mouse.position_in(event.tab.id)
        if point is not None:
            await self._render(
                CursorStateEvent(x=point.x, y=point.y, target_id=event.tab.id)
            )
        else:
            try:
                async with asyncio.timeout(2.5):
                    await self._state.view.restore(event.tab)
            except (BrowserError, TimeoutError):
                logger.debug("Presentation restoration unavailable")

    async def _render(self, event: LiveEvent) -> None:
        if isinstance(event, (InputEvent, DownloadProgressedEvent, WorkPresentedEvent)):
            await self._present(event)

    async def _browser_event(self, event: BrowserEvent) -> None:
        if isinstance(event, (ActivityStartedEvent, ActivityFinishedEvent)):
            if self._state.view is None:
                return
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
        if receipt := project(event):
            # Facts enrich the same tool receipt rather than creating a second card.
            for active in self._state.running.values():
                if (
                    active.kind is receipt.kind
                    and receipt.kind is not ActionKind.HANDLE_DIALOG
                ):
                    receipt = replace(
                        receipt,
                        work_id=active.work_id,
                        call_id=active.call_id,
                        tool_name=active.tool_name,
                        detail=receipt.detail or active.detail,
                        preview=receipt.preview or active.preview,
                        source_path=receipt.source_path or active.source_path,
                        target_id=receipt.target_id or active.target_id,
                        document_id=receipt.document_id or active.document_id,
                    )
                    break
            await self._emit_work(receipt)
        if isinstance(event, ObservationCapturedEvent):
            await self._screenshot_captured(event)

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
            async with asyncio.timeout(2.5):
                await view.show(tab, event)
        except (BrowserError, TimeoutError):
            view.suspend()
            # Presentation cannot turn successful native input into failed input.
            logger.debug("Input presentation unavailable for the current document")

    @hook(ExecuteTool)
    async def _work(self, event: ExecuteTool, next_: Next[ToolResult]) -> ToolResult:
        metadata = event.tool.metadata.get(BrowserToolMetadata) if event.tool else None
        if metadata is None:
            return await next_()
        self._state.handled.add(event.call.id)
        receipt = work.started(self._redact(event.call), metadata.kind)
        tab = self._browser.active_tab
        receipt = replace(receipt, target_id=tab.id, document_id=tab.document_id)
        if metadata.kind in {
            ActionKind.EXTRACT_CONTENT,
            ActionKind.JAVASCRIPT,
            ActionKind.SCREENSHOT,
            ActionKind.GO_BACK,
            ActionKind.GO_FORWARD,
            ActionKind.RELOAD,
        }:
            receipt = replace(receipt, source_url=tab.url)
        self._state.running[event.call.id] = receipt
        shown = (
            metadata.kind in work.SILENT_WORK
            and metadata.kind is not ActionKind.HANDLE_DIALOG
        )
        started_at = monotonic()
        try:
            if shown:
                await self._emit_work(receipt)
            result = await next_()
        except asyncio.CancelledError:
            await self._emit_work(
                work.finished(
                    receipt,
                    ToolResult("Cancelled", ToolStatus.CANCELLED),
                    elapsed=monotonic() - started_at,
                )
            )
            raise
        except Exception as error:
            await self._emit_work(
                work.finished(
                    receipt,
                    ToolResult.error(self._redact(str(error))),
                    elapsed=monotonic() - started_at,
                )
            )
            raise
        finally:
            self._state.running.pop(event.call.id, None)
        if shown or result.is_error:
            context = self._state.context
            extraction = (
                context[BrowserPerception].extracted_content
                if metadata.kind is ActionKind.EXTRACT_CONTENT
                and context is not None
                and BrowserPerception in context
                else None
            )
            completed = work.finished(
                receipt,
                self._redact(result),
                elapsed=monotonic() - started_at,
                extraction=self._redact(extraction),
            )
            if metadata.kind is ActionKind.SCREENSHOT and not result.is_error:
                if previous := self._state.screenshot:
                    await self._emit_work(
                        replace(
                            previous,
                            phase=WorkPhase.CANCELLED,
                            detail="Replaced by a newer screenshot request",
                        )
                    )
                self._state.screenshot = completed
            await self._emit_work(completed)
        return result

    def _redact[T](self, value: T) -> T:
        context = self._state.context
        return (
            context[Secrets].redact(value)
            if context is not None and Secrets in context
            else value
        )

    @hook(ToolCallFinishedEvent)
    async def _unexecuted(self, event: ToolCallFinishedEvent) -> None:
        if event.call_id in self._state.handled:
            self._state.handled.discard(event.call_id)
            return
        if event.result.is_error:
            result = self._redact(event.result)
            await self._emit_work(
                WorkPresentedEvent(
                    work_id=f"tool:{event.call_id}",
                    call_id=event.call_id,
                    tool_name=event.call.name,
                    kind=None,
                    title="Tool not executed",
                    phase=WorkPhase.FAILED,
                    detail=f"{event.call.name} · {result.status.value}",
                    preview=work.clipped(result.text),
                )
            )

    async def _emit_work(self, event: WorkPresentedEvent) -> None:
        # The browser event boundary also applies configured secret redaction.
        await self._events.emit(replace(event, at=monotonic()))

    async def _screenshot_captured(self, event: ObservationCapturedEvent) -> None:
        receipt = self._state.screenshot
        context = self._state.context
        if receipt is None or context is None or BrowserPerception not in context:
            return
        snapshot = context[BrowserPerception].snapshot
        if snapshot is None or snapshot.id != event.observation_id:
            return
        self._state.screenshot = None
        image = snapshot.image
        region = snapshot.geometry
        await self._emit_work(
            replace(
                receipt,
                phase=WorkPhase.COMPLETED if image else WorkPhase.WARNING,
                detail="Screenshot captured"
                if image
                else "Observation captured without an image",
                target_id=snapshot.tab_id,
                document_id=snapshot.document_id,
                source_url=snapshot.url,
                image_url=await asyncio.to_thread(thumbnail, image) if image else "",
                region=CaptureRegion(
                    x=region.x, y=region.y, width=region.width, height=region.height
                )
                if region
                else CaptureRegion(
                    x=0, y=0, width=snapshot.width, height=snapshot.height
                )
                if snapshot.width > 0 and snapshot.height > 0
                else receipt.region,
            )
        )

    @hook(TurnEndedEvent)
    async def _turn_ended(self, _event: TurnEndedEvent) -> None:
        self._state.handled.clear()
        if receipt := self._state.screenshot:
            self._state.screenshot = None
            await self._emit_work(
                replace(
                    receipt,
                    phase=WorkPhase.CANCELLED,
                    detail="Turn ended before the requested screenshot was captured",
                )
            )

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
