import asyncio
import math
from dataclasses import dataclass, field
from typing import Annotated
from uuid import uuid4

from harnessed import (
    Context,
    Inject,
    Plugin,
    PluginState,
    SystemSection,
    ToolChain,
    ToolContext,
    hook,
)
from harnessed.core.prompt.context import DynamicContext
from harnessed.core.tools import ToolRegistry
from harnessed.events import AgentControlChangedEvent, ControlState
from harnessed.hooks import Next, PreStep, StepDecision
from pydantic import Field, TypeAdapter, ValidationError

from browserrig.browser.base import Browser, BrowserEvents
from browserrig.events import (
    HANDOFF_EVENTS,
    BrowserEvent,
    EventKind,
    HandoffFinishedEvent,
    HandoffRequestedEvent,
    HandoffStatus,
)
from browserrig.nudges import Nudges
from browserrig.observation import Observe
from browserrig.observation.models import Snapshot
from browserrig.secrets import Secrets

from .changes import page_changes, page_url
from .models import HandoffCallback, HandoffReceipt, HumanResponse

_HISTORY = TypeAdapter(list[HandoffReceipt])


@dataclass
class _Transfer:
    request: HandoffRequestedEvent
    before: Snapshot | None
    nudges: Nudges | None
    events: dict[str, int] = field(default_factory=dict)


@dataclass
class _State:
    current: _Transfer | None = None
    resume_pending: bool = False


class HumanHandoff(
    Plugin,
    provides=True,
    needs=(Browser, BrowserEvents, Observe, DynamicContext, ToolRegistry),
):
    """Opt-in human control with measured receipts and durable, bounded context.

    The async callback owns the host UI and returns only after the human finishes.
    Do not call session.pause() from that callback: the current tool is already waiting.
    """

    events = HANDOFF_EVENTS
    _state = PluginState(_State)
    _browser: Inject[Browser]
    _events: Inject[BrowserEvents]
    _observe: Inject[Observe]
    _context: Inject[DynamicContext]

    def __init__(
        self,
        *,
        ask: HandoffCallback,
        timeout: float = 900,
        track_pauses: bool = True,
        history_limit: int = 5,
    ) -> None:
        super().__init__()
        if not callable(ask):
            raise TypeError("ask must be an async handoff callback")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not isinstance(track_pauses, bool):
            raise TypeError("track_pauses must be a bool")
        if (
            isinstance(history_limit, bool)
            or not isinstance(history_limit, int)
            or not 1 <= history_limit <= 20
        ):
            raise ValueError("history_limit must be between 1 and 20")
        self.ask = ask
        self.timeout = timeout
        self.track_pauses = track_pauses
        self.history_limit = history_limit

    usage = SystemSection(
        title="Human handoff",
        text=(
            "Use request_human when a person must log in, confirm 2FA, or complete a blocked "
            "browser step. The tool waits for the person. Its receipt distinguishes the human's "
            "report from measured page changes. After human control or a host pause, inspect "
            "the fresh browser observation and use its references before acting. A done report "
            "does not prove success. Verify the requested state before repeating login or "
            "submission. Recent handoffs remain in browser.handoffs across compaction; current "
            "page observations take precedence over these historical reports. Never request "
            "passwords, recovery codes or other credential values in the response note."
        ),
    )

    async def setup(self, ctx: Context, tools: Inject[ToolRegistry]) -> None:
        # Override the loop's ordinary 30s tool timeout for this mount's human wait.
        tools.register(
            self.request_human,
            owner=ctx,
            description=(
                "Hand browser control to a human and wait for completion, decline or timeout. "
                "Describe what they should do and the expected visible result. Then inspect "
                "the receipt and the next browser observation before continuing."
            ),
            timeout=self.timeout + 60,
            readonly=True,
            chain=ToolChain.STOP_AFTER,
        )
        ctx.effect(self._release)

    def _release(self) -> None:
        transfer, self._state.current = self._state.current, None
        self._state.resume_pending = False
        if transfer is not None and transfer.nudges is not None:
            transfer.nudges.end_human_control()

    async def _capture(self) -> Snapshot | None:
        try:
            return await self._observe.probe(self._browser.active_tab)
        # Capture strategies are extensible; failure must not prevent human control.
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    async def _begin(
        self,
        request: HandoffRequestedEvent,
        nudges: Nudges | None,
        *,
        probe: bool = True,
    ) -> None:
        # A running pause is acknowledged before async event observers finish. Publish
        # its baseline synchronously so an immediate resume cannot overtake this hook.
        before = self._observe.snapshot
        transfer = _Transfer(request, before, nudges)
        self._state.current = transfer
        if nudges is not None:
            await nudges.begin_human_control()
        await self._events.emit(request)
        if probe:
            transfer.before = await self._capture()

    async def request_human(
        self,
        reason: Annotated[str, Field(min_length=1, max_length=2000)],
        expected_state: Annotated[str, Field(max_length=1000)] = "",
        *,
        context: ToolContext,
        nudges: Inject[Nudges | None],
        secrets: Inject[Secrets | None],
    ) -> str:
        async with self._browser.action_lock:
            tab = self._browser.active_tab
            request = HandoffRequestedEvent(
                handoff_id=uuid4().hex,
                reason=reason,
                expected_state=expected_state,
                call_id=context.call.id,
                target_id=tab.id,
                document_id=tab.document_id,
                browser_id=self._events.browser_id,
            )
            request = secrets.redact(request) if secrets else request
            try:
                await self._begin(request, nudges)
                try:
                    async with asyncio.timeout(self.timeout):
                        response = await self.ask(request)
                    if not isinstance(response, HumanResponse):
                        raise TypeError("Handoff callbacks must return HumanResponse")
                except TimeoutError:
                    return await self._finish("timeout", secrets=secrets)
                except Exception:  # pylint: disable=broad-exception-caught
                    return await self._finish(
                        "failed",
                        note="The host callback failed; completion is unknown.",
                        secrets=secrets,
                    )
                return await self._finish(
                    response.status, note=response.note, secrets=secrets
                )
            except asyncio.CancelledError:
                if self._state.current is not None:
                    await self._finish("cancelled", secrets=secrets, capture=False)
                raise
            finally:
                self._release()

    async def _finish(
        self,
        status: HandoffStatus,
        *,
        note: str = "",
        secrets: Secrets | None = None,
        capture: bool = True,
    ) -> str:
        transfer = self._state.current
        assert transfer is not None
        after = await self._capture() if capture else None
        changes = (
            *page_changes(transfer.before, after),
            *(
                f"During human control: {count} {kind} event(s)."
                for kind, count in transfer.events.items()
            ),
        )
        request = transfer.request
        if request.source == "pause":
            changes = (
                "Comparison baseline: the last agent observation before the host pause.",
                *changes,
            )
        event = HandoffFinishedEvent(
            handoff_id=request.handoff_id,
            status=status,
            note=note,
            changes=changes,
            source=request.source,
            call_id=request.call_id,
            target_id=after.tab_id if after else request.target_id,
            document_id=after.document_id if after else request.document_id,
        )
        event = secrets.redact(event) if secrets else event
        await self._events.emit(event)
        receipt = HandoffReceipt(
            handoff_id=request.handoff_id,
            source=request.source,
            status=status,
            reason=request.reason,
            expected_state=request.expected_state,
            human_note=event.note,
            changes=event.changes,
            current_url=page_url(after.url) if after else None,
        )
        receipt = secrets.redact(receipt) if secrets else receipt
        previous = self._context.values.get("browser.handoffs", "[]")
        try:
            history = _HISTORY.validate_json(previous)
        except ValidationError:
            history = []
        history = [*history, receipt][-self.history_limit :]
        await self._context.set(
            "browser.handoffs", _HISTORY.dump_json(history).decode()
        )
        self._observe.invalidate()
        self._release()
        return receipt.model_dump_json()

    @hook(AgentControlChangedEvent)
    async def _control(
        self,
        event: AgentControlChangedEvent,
        nudges: Inject[Nudges | None],
    ) -> None:
        if not self.track_pauses:
            return
        if event.state == ControlState.PAUSED and self._state.current is None:
            tab = self._browser.active_tab
            await self._begin(
                HandoffRequestedEvent(
                    handoff_id=uuid4().hex,
                    reason="The host paused the agent; external browser changes may follow.",
                    source="pause",
                    target_id=tab.id,
                    document_id=tab.document_id,
                ),
                nudges,
                probe=False,
            )
        elif event.state == ControlState.ACTIVE and self._state.current is not None:
            self._state.resume_pending = self._state.current.request.source == "pause"

    @hook(PreStep, priority=-50)
    async def _resume(
        self,
        _event: PreStep,
        next_: Next[StepDecision],
        secrets: Inject[Secrets | None],
    ) -> StepDecision:
        if self._state.resume_pending:
            await self._finish("resumed", secrets=secrets)
        return await next_()

    @hook(BrowserEvent)
    def _changed(self, event: BrowserEvent) -> None:
        if event.type not in (
            EventKind.TAB_OPENED,
            EventKind.TAB_CLOSED,
            EventKind.DIALOG_OPENED,
            EventKind.DOWNLOAD_COMPLETED,
        ):
            return
        if event.browser_id and event.browser_id != self._events.browser_id:
            return
        transfer = self._state.current
        if transfer is not None:
            key = str(event.type).removeprefix("browser.")
            transfer.events[key] = transfer.events.get(key, 0) + 1
