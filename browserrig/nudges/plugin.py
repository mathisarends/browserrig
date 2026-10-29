from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml
from harnessed import Inject, Observation, Plugin, PluginState, SessionLog, hook
from harnessed.events import ObservationForm, ObservationsIncludedEvent

from browserrig.browser.base import Browser
from browserrig.core.kinds import ActionKind, ReadinessStatus
from browserrig.events import (
    NUDGE_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    DialogOpenedEvent,
    DownloadCompletedEvent,
    NudgeExpiredEvent,
    NudgeIncludedEvent,
    NudgeQueuedEvent,
    ObservationCapturedEvent,
    ReadinessDegradedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)

if TYPE_CHECKING:
    from browserrig.observation.models import Snapshot


@dataclass
class _TabState:
    pending: ActionFinishedEvent | None = None
    starts: dict[str, float] = field(default_factory=dict)


@dataclass
class _State:
    queued: dict[str, NudgeQueuedEvent] = field(default_factory=dict)
    tabs: dict[str, _TabState] = field(default_factory=dict)
    effect_at: float = 0


class Nudges(Plugin, provides=True, needs=(SessionLog, Browser)):
    events = NUDGE_EVENTS
    _state = PluginState(_State)

    def __init__(self, *, max_hints: int = 5, max_chars: int = 2000) -> None:
        super().__init__()
        if not 1 <= max_hints <= 20 or not 100 <= max_chars <= 10000:
            raise ValueError("Invalid nudge limits")
        self._max_hints, self._max_chars = max_hints, max_chars

    async def setup(self, log: Inject[SessionLog]) -> None:
        # Reconstruct audit state without redispatching live browser side effects.
        for event in log.events:
            match event:
                case NudgeQueuedEvent(key=key):
                    self._state.queued[key] = event
                case NudgeIncludedEvent(nudge_ids=ids):
                    self._remove(ids)
                case NudgeExpiredEvent(nudge_id=nudge_id):
                    self._remove((nudge_id,))

    def _remove(self, ids: tuple[str, ...]) -> None:
        self._state.queued = {
            key: value for key, value in self._state.queued.items() if value.nudge_id not in ids
        }

    async def queue(
        self,
        browser: Browser,
        text: str,
        *,
        key: str,
        cause_id: str,
        target_id: str = "",
        document_id: str = "",
    ) -> None:
        if previous := self._state.queued.get(key):
            if previous.text == text:
                return
            await browser.emit(NudgeExpiredEvent(nudge_id=previous.nudge_id))
        event = NudgeQueuedEvent(
            nudge_id=uuid4().hex,
            key=key,
            text=text[: self._max_chars],
            cause_id=cause_id,
            browser_id=browser.id,
            target_id=target_id,
            document_id=document_id,
        )
        self._state.queued[key] = event
        while len(self._state.queued) > self._max_hints * 4:
            oldest = next(iter(self._state.queued))
            removed = self._state.queued.pop(oldest)
            await browser.emit(NudgeExpiredEvent(nudge_id=removed.nudge_id))
        await browser.emit(event)

    @hook(ActionStartedEvent)
    async def _on_start(self, event: ActionStartedEvent) -> None:
        state = self._state.tabs.setdefault(event.target_id, _TabState())
        state.starts[event.action_id] = event.at

    @hook(ActionFinishedEvent)
    async def _on_action(self, event: ActionFinishedEvent) -> None:
        state = self._state.tabs.setdefault(event.target_id, _TabState())
        if state.pending is not None:
            state.starts.pop(state.pending.action_id, None)
        state.pending = None
        if not event.expects_change and event.kind != ActionKind.CLICK:
            state.starts.pop(event.action_id, None)
            if not state.starts:
                self._state.tabs.pop(event.target_id, None)
            return
        state.pending = event

    @hook(ActionFailedEvent)
    async def _on_failure(self, event: ActionFailedEvent) -> None:
        self._state.tabs.pop(event.target_id, None)

    @hook(TabClosedEvent)
    async def _on_tab_closed(self, event: TabClosedEvent) -> None:
        self._state.tabs.pop(event.target_id, None)

    @hook(ObservationCapturedEvent)
    async def _on_observation(
        self, event: ObservationCapturedEvent, browser: Inject[Browser]
    ) -> None:
        state = self._state.tabs.get(event.target_id)
        if state is None or state.pending is None:
            return
        action, state.pending = state.pending, None
        started_at = state.starts.pop(action.action_id, action.at)
        if not state.starts:
            self._state.tabs.pop(event.target_id, None)
        same_page = (
            action.before.url == event.url == action.after_url
            and action.before.document_id == event.document_id
            and action.target_id == event.target_id
        )
        if not same_page:
            return
        if (
            action.kind == ActionKind.CLICK
            and not action.prepared_scroll
            and abs(event.scroll_y - action.before.scroll_y) >= 50
        ):
            delta = event.scroll_y - action.before.scroll_y
            await self.queue(
                browser,
                f"The page scrolled {abs(delta):.0f}px "
                f"{'down' if delta > 0 else 'up'} after the click.",
                key="unexpected_scroll",
                cause_id=action.action_id,
                target_id=event.target_id,
                document_id=event.document_id,
            )
        if (
            action.expects_change
            and action.before.fingerprint == event.fingerprint
            and self._state.effect_at < started_at
            and event.readiness == ReadinessStatus.READY
        ):
            await self.queue(
                browser,
                "The last action produced no observable page change; inspect before repeating it.",
                key="no_progress",
                cause_id=action.action_id,
                target_id=event.target_id,
                document_id=event.document_id,
            )

    @hook(TabOpenedEvent)
    async def _on_tab(self, event: TabOpenedEvent, browser: Inject[Browser]) -> None:
        self._state.effect_at = event.at
        await self.queue(
            browser,
            f"A tab opened: {event.target_id}. The active tab changes only when selected.",
            key=f"tab:{event.target_id}",
            cause_id=event.target_id,
        )

    @hook(DownloadCompletedEvent)
    async def _on_download(self, event: DownloadCompletedEvent, browser: Inject[Browser]) -> None:
        self._state.effect_at = event.at
        await self.queue(
            browser,
            f"Download completed: {event.filename} ({event.size} bytes).",
            key=f"download:{event.download_id}",
            cause_id=event.download_id,
        )

    @hook(DialogOpenedEvent)
    async def _on_dialog(self, event: DialogOpenedEvent, browser: Inject[Browser]) -> None:
        self._state.effect_at = event.at
        await self.queue(
            browser,
            f"A {event.kind} dialog blocks this tab: {event.message}",
            key=f"dialog:{event.target_id}",
            cause_id=event.target_id,
            target_id=event.target_id,
        )

    @hook(ReadinessDegradedEvent)
    async def _on_degraded(self, event: ReadinessDegradedEvent, browser: Inject[Browser]) -> None:
        await self.queue(
            browser,
            f"Readiness is limited: {event.reason}",
            key="readiness",
            cause_id=event.readiness_id,
            target_id=event.target_id,
            document_id=event.document_id,
        )

    async def project(self, snapshot: Snapshot, browser: Browser) -> Observation:
        selected, size = [], 0
        for key, event in tuple(self._state.queued.items()):
            expired = (
                event.browser_id != browser.id
                or bool(event.target_id and event.target_id != snapshot.tab_id)
                or bool(event.document_id and event.document_id != snapshot.document_id)
            )
            if expired:
                self._state.queued.pop(key, None)
                await browser.emit(NudgeExpiredEvent(nudge_id=event.nudge_id))
                continue
            if size + len(event.text) <= self._max_chars and len(selected) < self._max_hints:
                selected.append({"id": event.nudge_id, "text": event.text})
                size += len(event.text)
        return Observation(
            source="browser.nudges",
            full=yaml.safe_dump({"nudges": selected}, sort_keys=False, allow_unicode=True),
            summary="Previous browser hints",
            refs=tuple(item["id"] for item in selected),
        )

    @hook(ObservationsIncludedEvent)
    async def _on_request(self, event: ObservationsIncludedEvent, browser: Inject[Browser]) -> None:
        refs = {
            ref
            for observation in event.observations
            if observation.source == "browser.nudges" and observation.form is ObservationForm.FULL
            for ref in observation.refs
        }
        included = tuple(
            item.nudge_id for item in self._state.queued.values() if item.nudge_id in refs
        )
        if included:
            await browser.emit(NudgeIncludedEvent(nudge_ids=included, request_id=event.request_id))
            self._remove(included)
