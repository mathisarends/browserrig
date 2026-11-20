import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any

from harnessed import Plugin
from harnessed.events import ToolCallFinishedEvent, TurnEndedEvent, TurnStartedEvent
from harnessed.hooks import ExecuteTool, Next
from harnessed.kernel import PluginScope, PluginState, needs
from harnessed.models import ToolResult, ToolStatus
from harnessed.tools import envelope_value

from browserrig.browser import Browser, BrowserEvents, TabChanged
from browserrig.core import (
    ActionKind,
    ActionLabel,
    BrowserCoordination,
    BrowserToolMetadata,
    ViewportSize,
)
from browserrig.events import (
    INPUT_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    BrowserEvent,
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
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

from . import contributions, scenes, work
from .contributions import Contribution
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
from .status import ProjectStatus, StatusFact

# How each intent is staged around its step.
type SceneHandler = Callable[[scenes.Scene, Any, scenes.Step], Awaitable[Any]]
_SCENES: dict[type, tuple[type[Contribution], SceneHandler]] = {
    DomScrollIntent: (contributions.DomScroll, scenes.dom_scroll),
    SearchIntent: (contributions.Find, scenes.search),
    NavigateIntent: (contributions.Navigation, scenes.navigate),
    ControlIntent: (contributions.Navigation, scenes.press),
    WaitIntent: (contributions.Activity, scenes.wait),
    OpenFileIntent: (contributions.FileTransfer, scenes.open_file),
    UploadIntent: (contributions.FileTransfer, scenes.upload),
}


@dataclass
class _Staging:
    """One session's running tool receipts and the screenshot still awaiting capture."""

    context: PluginScope | None = None
    screenshot: WorkPresentedEvent | None = None
    running: dict[str, WorkPresentedEvent] = field(default_factory=dict)
    handled: set[str] = field(default_factory=set)
    status: ProjectStatus = field(default_factory=ProjectStatus)


class Choreography(Plugin, slot="browserrig.choreography", provides=True):
    """Stage the browser for people watching: visible input and browser UI as events.

    Select contributions with `only` (instances) or `without` (types). By default all
    built-in contributions are active.

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

    def __init__(
        self,
        *,
        only: Sequence[Contribution] | None = None,
        without: Sequence[type[Contribution]] | None = None,
    ) -> None:
        super().__init__()
        self._selected = contributions.select(only, without)
        self._scenes = {
            intent: handler
            for intent, (group, handler) in _SCENES.items()
            if group in self._selected
        }

    async def setup(self, scope: PluginScope) -> None:
        self._state.context = scope
        scope.effect(
            self._input.present(
                Stage(
                    pointer=contributions.Pointer in self._selected,
                    keyboard=contributions.Keyboard in self._selected,
                    tabs=contributions.TabSwitch in self._selected,
                )
            )
        )
        if contributions.Pointer in self._selected:
            scope.on(TurnStartedEvent, self._publish_cursor)
            scope.on(TabChanged, self._republish_cursor)
        if self._scenes:
            scope.on(Perform, self._stage)
        if contributions.TargetHighlight in self._selected:
            scope.on(TargetLocated, self._highlight)
        if contributions.Work in self._selected:
            scope.on(BrowserEvent, self._browser_event)
            scope.on(ExecuteTool, self._work)
            scope.on(ToolCallFinishedEvent, self._unexecuted)
            scope.on(TurnEndedEvent, self._turn_ended)
        if contributions.Download in self._selected:
            scope.on(DownloadStartedEvent, self._status)
            scope.on(DownloadProgressedEvent, self._status)
            scope.on(DownloadCompletedEvent, self._status)
            scope.on(DownloadFailedEvent, self._status)
            scope.on(DownloadCanceledEvent, self._status)
        if contributions.Activity in self._selected:
            scope.on(ActivityStartedEvent, self._status)
            scope.on(ActivityFinishedEvent, self._status)
        if contributions.FileTransfer in self._selected:
            scope.on(FilesUploadedEvent, self._status)

    async def _publish_cursor(self, _event: TurnStartedEvent) -> None:
        await self._input.mouse.publish_cursor()

    async def _republish_cursor(self, event: TabChanged) -> None:
        # A new document or tab shows nothing yet; viewers learn where the pointer rests.
        if not event.settled or event.tab.closed:
            return
        if event.tab.id != self._browser.active_tab.id:
            return
        if self._input.mouse.position_in(event.tab.id) is not None:
            await self._input.mouse.publish_cursor()

    async def _status(self, event: StatusFact) -> None:
        if presented := self._state.status(event):
            await self._emit(presented)

    async def _browser_event(self, event: BrowserEvent) -> None:
        if receipt := project(event):
            # Facts enrich the same tool receipt rather than creating a second card.
            if active := self._owner(receipt):
                receipt = replace(
                    receipt,
                    work_id=active.work_id,
                    call_id=active.call_id,
                    tool_name=active.tool_name,
                    label=active.label,
                    detail=receipt.detail or active.detail,
                    preview=receipt.preview or active.preview,
                    source_path=receipt.source_path or active.source_path,
                    target_id=receipt.target_id or active.target_id,
                    document_id=receipt.document_id or active.document_id,
                )
            await self._emit(receipt)
        if isinstance(event, ObservationCapturedEvent):
            await self._screenshot_captured(event)

    def _owner(self, receipt: WorkPresentedEvent) -> WorkPresentedEvent | None:
        """The running tool receipt a projected fact belongs to, by call when known."""
        if receipt.kind is ActionKind.HANDLE_DIALOG:
            return None
        if receipt.call_id:
            return self._state.running.get(receipt.call_id)
        return next(
            (
                active
                for active in self._state.running.values()
                if active.kind is receipt.kind
            ),
            None,
        )

    async def _work(self, event: ExecuteTool, next_: Next[ToolResult]) -> ToolResult:
        metadata = event.tool.metadata.get(BrowserToolMetadata) if event.tool else None
        if metadata is None:
            return await next_()
        self._state.handled.add(event.call.id)
        receipt = work.started(self._redact(event.call), metadata.kind)
        label = event.envelope.get(ActionLabel)
        if label is not None:
            receipt = replace(receipt, label=self._redact(label.action_label))
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

    async def _unexecuted(self, event: ToolCallFinishedEvent) -> None:
        if event.call_id in self._state.handled:
            self._state.handled.discard(event.call_id)
            return
        if event.result.is_error:
            result = self._redact(event.result)
            label = envelope_value(event.call, ActionLabel)
            text = self._redact(label.action_label) if label is not None else ""
            await self._emit(
                WorkPresentedEvent(
                    work_id=f"tool:{event.call_id}",
                    call_id=event.call_id,
                    tool_name=event.call.name,
                    kind=None,
                    title="Tool not executed",
                    label=text,
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

    async def _stage(self, event: Perform, next_: Next[Any]) -> Any:
        staged = self._scenes.get(type(event.intent))
        if staged is None:
            return await next_()
        pointer = self._input.mouse.position_in(event.tab.id)
        scene = scenes.Scene(event.tab, event.action_id, pointer)
        return await staged(scene, event.intent, next_)

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
