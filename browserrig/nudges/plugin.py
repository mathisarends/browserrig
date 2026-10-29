from dataclasses import dataclass, field
from uuid import uuid4

import yaml
from harnessed import Inject, Observation, Plugin, PluginState, SessionLog, hook
from harnessed.events import ObservationForm, ObservationsIncludedEvent

from browserrig.browser.base import Browser
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
    TabOpenedEvent,
)
from browserrig.kinds import ActionKind, ReadinessStatus
from browserrig.observation.models import Snapshot


@dataclass
class _State:
    queued: dict[str, NudgeQueuedEvent] = field(default_factory=dict)
    pending: dict[str, ActionFinishedEvent] = field(default_factory=dict)
    starts: dict[str, float] = field(default_factory=dict)
    effect_at: float = 0


class Nudges(Plugin, provides=True):
    events = NUDGE_EVENTS
    state = PluginState(_State)

    def __init__(self, *, max_hints: int = 5, max_chars: int = 2000) -> None:
        super().__init__()
        if not 1 <= max_hints <= 20 or not 100 <= max_chars <= 10000:
            raise ValueError("Invalid nudge limits")
        self.max_hints, self.max_chars = max_hints, max_chars

    async def setup(self, log: Inject[SessionLog]) -> None:
        # Reconstruct audit state without redispatching live browser side effects.
        for event in log.events:
            match event:
                case NudgeQueuedEvent(key=key):
                    self.state.queued[key] = event
                case NudgeIncludedEvent(nudge_ids=ids):
                    self._remove(ids)
                case NudgeExpiredEvent(nudge_id=nudge_id):
                    self._remove((nudge_id,))

    def _remove(self, ids: tuple[str, ...]) -> None:
        self.state.queued = {
            key: value for key, value in self.state.queued.items() if value.nudge_id not in ids
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
        if previous := self.state.queued.get(key):
            if previous.text == text:
                return
            await browser.emit(NudgeExpiredEvent(nudge_id=previous.nudge_id))
        event = NudgeQueuedEvent(
            nudge_id=uuid4().hex,
            key=key,
            text=text[: self.max_chars],
            cause_id=cause_id,
            browser_id=browser.id,
            target_id=target_id,
            document_id=document_id,
        )
        self.state.queued[key] = event
        while len(self.state.queued) > self.max_hints * 4:
            oldest = next(iter(self.state.queued))
            removed = self.state.queued.pop(oldest)
            await browser.emit(NudgeExpiredEvent(nudge_id=removed.nudge_id))
        await browser.emit(event)

    @hook(ActionStartedEvent)
    async def on_start(self, event: ActionStartedEvent) -> None:
        self.state.starts[event.action_id] = event.at

    @hook(ActionFinishedEvent)
    async def on_action(self, event: ActionFinishedEvent) -> None:
        if previous := self.state.pending.pop(event.target_id, None):
            self.state.starts.pop(previous.action_id, None)
        if not event.expects_change and event.kind != ActionKind.CLICK:
            self.state.starts.pop(event.action_id, None)
            return
        self.state.pending[event.target_id] = event

    @hook(ActionFailedEvent)
    async def on_failure(self, event: ActionFailedEvent) -> None:
        self.state.starts.pop(event.action_id, None)
        self.state.pending.pop(event.target_id, None)

    @hook(ObservationCapturedEvent)
    async def on_observation(
        self, event: ObservationCapturedEvent, browser: Inject[Browser]
    ) -> None:
        action = self.state.pending.pop(event.target_id, None)
        if action is None:
            return
        started_at = self.state.starts.pop(action.action_id, action.at)
        same_page = (
            action.before_url == event.url == action.after_url
            and action.before_document == event.document_id
            and action.target_id == event.target_id
        )
        if not same_page:
            return
        if (
            action.kind == ActionKind.CLICK
            and not action.prepared_scroll
            and abs(event.scroll_y - action.before_scroll_y) >= 50
        ):
            delta = event.scroll_y - action.before_scroll_y
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
            and action.before_fingerprint == event.fingerprint
            and self.state.effect_at < started_at
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
    async def on_tab(self, event: TabOpenedEvent, browser: Inject[Browser]) -> None:
        self.state.effect_at = event.at
        await self.queue(
            browser,
            f"A tab opened: {event.target_id}. The active tab changes only when selected.",
            key=f"tab:{event.target_id}",
            cause_id=event.target_id,
        )

    @hook(DownloadCompletedEvent)
    async def on_download(self, event: DownloadCompletedEvent, browser: Inject[Browser]) -> None:
        self.state.effect_at = event.at
        await self.queue(
            browser,
            f"Download completed: {event.filename} ({event.size} bytes).",
            key=f"download:{event.download_id}",
            cause_id=event.download_id,
        )

    @hook(DialogOpenedEvent)
    async def on_dialog(self, event: DialogOpenedEvent, browser: Inject[Browser]) -> None:
        self.state.effect_at = event.at
        await self.queue(
            browser,
            f"A {event.kind} dialog blocks this tab: {event.message}",
            key=f"dialog:{event.target_id}",
            cause_id=event.target_id,
            target_id=event.target_id,
        )

    @hook(ReadinessDegradedEvent)
    async def on_degraded(self, event: ReadinessDegradedEvent, browser: Inject[Browser]) -> None:
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
        for key, event in tuple(self.state.queued.items()):
            expired = (
                event.browser_id != browser.id
                or bool(event.target_id and event.target_id != snapshot.tab_id)
                or bool(event.document_id and event.document_id != snapshot.document_id)
            )
            if expired:
                self.state.queued.pop(key, None)
                await browser.emit(NudgeExpiredEvent(nudge_id=event.nudge_id))
                continue
            if size + len(event.text) <= self.max_chars and len(selected) < self.max_hints:
                selected.append({"id": event.nudge_id, "text": event.text})
                size += len(event.text)
        return Observation(
            source="browser.nudges",
            full=yaml.safe_dump({"nudges": selected}, sort_keys=False, allow_unicode=True),
            summary="Previous browser hints",
            refs=tuple(item["id"] for item in selected),
        )

    @hook(ObservationsIncludedEvent)
    async def on_request(self, event: ObservationsIncludedEvent, browser: Inject[Browser]) -> None:
        refs = {
            ref
            for observation in event.observations
            if observation.source == "browser.nudges" and observation.form is ObservationForm.FULL
            for ref in observation.refs
        }
        included = tuple(
            item.nudge_id for item in self.state.queued.values() if item.nudge_id in refs
        )
        if included:
            await browser.emit(NudgeIncludedEvent(nudge_ids=included, request_id=event.request_id))
            self._remove(included)
