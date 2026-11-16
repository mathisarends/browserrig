import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any

from harnessed import Plugin, PluginState, ToolResult, ToolStatus, hook
from harnessed.events import ToolCallFinishedEvent, TurnEndedEvent, TurnStartedEvent
from harnessed.hooks import ExecuteTool, Next
from harnessed.kernel import PluginScope, needs

from browserrig.browser import Browser, BrowserEvents, TabChanged
from browserrig.core import (
    ActionKind,
    BrowserCoordination,
    BrowserToolMetadata,
    ViewportSize,
)
from browserrig.events import (
    INPUT_EVENTS,
    BrowserEvent,
    DownloadProgressedEvent,
    ObservationCapturedEvent,
)
from browserrig.input import Input
from browserrig.observation import BrowserPerception
from browserrig.secrets import Secrets
from browserrig.tools import (
    ControlIntent,
    DomScrollIntent,
    NavigateIntent,
    OpenFileIntent,
    Perform,
    SearchIntent,
    TargetLocated,
    UploadIntent,
    WaitIntent,
)

from . import scenes, work
from .events import (
    SCENE_EVENTS,
    CaptureRegion,
    HighlightElementEvent,
    PresentedEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from .images import thumbnail
from .projection import project
from .stage import Stage
from .status import StatusFact, StatusProjection

# How each intent is staged around its step.
_SCENES: dict[type, Callable[[scenes.Scene, Any, scenes.Step], Awaitable[Any]]] = {
    DomScrollIntent: scenes.dom_scroll,
    SearchIntent: scenes.search,
    NavigateIntent: scenes.navigate,
    ControlIntent: scenes.press,
    WaitIntent: scenes.wait,
    OpenFileIntent: scenes.open_file,
    UploadIntent: scenes.upload,
}


@dataclass
class _Staging:
    """One session's running tool receipts and the screenshot still awaiting capture."""

    context: PluginScope | None = None
    screenshot: WorkPresentedEvent | None = None
    running: dict[str, WorkPresentedEvent] = field(default_factory=dict)
    handled: set[str] = field(default_factory=set)
    status: StatusProjection = field(default_factory=StatusProjection)


class Choreography(Plugin, slot="browserrig.choreography", provides=True):
    """Stage the browser for people watching: visible input and browser UI as events.

    Tools and input devices only describe what they do. This plugin streams input as
    live events, stages browser UI such as the address and find bars, highlights the
    elements tools act on and projects work, downloads, uploads and activities into
    `PresentedEvent`s. It draws nothing itself; viewers such as `ChoreographyOverlay`
    consume the events. How fast input runs is up to
    `InputPacing`. Without this plugin no input events are emitted.
    """

    events = INPUT_EVENTS + SCENE_EVENTS
    _state = PluginState(_Staging)
    _browser = needs(Browser)
    _input = needs(Input)
    _events = needs(BrowserEvents)
    _coordination = needs(BrowserCoordination)

    async def setup(self, scope: PluginScope) -> None:
        self._state.context = scope
        scope.on(BrowserEvent, self._browser_event)
        scope.on(DownloadProgressedEvent, self._status)
        # Each call installs now and registers its undo for teardown.
        scope.effect(self._input.present(Stage()))

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach late, so seed their cursor at turn start.
            await self._input.mouse.publish_cursor()

        scope.on(TurnStartedEvent, publish_cursor)

    @hook(TabChanged)
    async def _republish_cursor(self, event: TabChanged) -> None:
        # A new document or tab shows nothing yet; viewers learn where the pointer rests.
        if not event.settled or event.tab.closed:
            return
        if event.tab.id != self._browser.active_tab.id:
            return
        if self._input.mouse.position_in(event.tab.id) is not None:
            await self._input.mouse.publish_cursor()

    async def _status(self, event: StatusFact) -> None:
        if presented := self._state.status.project(event):
            await self._emit(presented)

    async def _browser_event(self, event: BrowserEvent) -> None:
        await self._status(event)
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
            await self._emit(receipt)
        if isinstance(event, ObservationCapturedEvent):
            await self._screenshot_captured(event)

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
            ActionKind.SEARCH_PAGE,
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
                await self._emit(receipt)
            result = await next_()
        except asyncio.CancelledError:
            await self._emit(
                work.finished(
                    receipt,
                    ToolResult("Cancelled", ToolStatus.CANCELLED),
                    elapsed=monotonic() - started_at,
                )
            )
            raise
        except Exception as error:
            await self._emit(
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
            completed = work.finished(
                receipt,
                self._redact(result),
                elapsed=monotonic() - started_at,
            )
            if metadata.kind is ActionKind.SCREENSHOT and not result.is_error:
                if previous := self._state.screenshot:
                    await self._emit(
                        replace(
                            previous,
                            phase=WorkPhase.CANCELLED,
                            detail="Replaced by a newer screenshot request",
                        )
                    )
                self._state.screenshot = completed
            await self._emit(completed)
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
            await self._emit(
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

    async def _emit(self, event: PresentedEvent) -> None:
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
        geometry = snapshot.geometry
        viewport = (
            ViewportSize(width=snapshot.width, height=snapshot.height)
            if snapshot.width > 0 and snapshot.height > 0
            else None
        )
        if geometry:
            region = CaptureRegion(
                x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height
            )
        elif viewport:
            region = CaptureRegion(
                x=0, y=0, width=viewport.width, height=viewport.height
            )
        else:
            region = receipt.region
        await self._emit(
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
                region=region,
                viewport=viewport or receipt.viewport,
            )
        )

    @hook(TurnEndedEvent)
    async def _turn_ended(self, _event: TurnEndedEvent) -> None:
        self._state.handled.clear()
        if receipt := self._state.screenshot:
            self._state.screenshot = None
            await self._emit(
                replace(
                    receipt,
                    phase=WorkPhase.CANCELLED,
                    detail="Turn ended before the requested screenshot was captured",
                )
            )

    @hook(Perform)
    async def _stage(self, event: Perform, next_: Next[Any]) -> Any:
        staged = _SCENES.get(type(event.intent))
        if staged is None:
            return await next_()
        pointer = self._input.mouse.position_in(event.tab.id)
        scene = scenes.Scene(event.tab, event.action_id, pointer)
        return await staged(scene, event.intent, next_)

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
