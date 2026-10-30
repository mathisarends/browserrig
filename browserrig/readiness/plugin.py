import asyncio
from dataclasses import dataclass, field

from harnessed import Context, Inject, Plugin, PluginState, hook
from harnessed.events import AgentControlChangedEvent, ControlState

from browserrig.browser.base import BrowserEvents
from browserrig.browser.tab import Tab
from browserrig.core.kinds import ReadinessPhase, ReadinessStage, ReadinessStatus
from browserrig.events import (
    READINESS_EVENTS,
)

from .config import ReadinessOptions
from .models import ReadinessReport
from .policies import DomReady, ReadinessPolicy
from .wait import wait_for_page


@dataclass
class _State:
    pending: dict[tuple[str, str, str, str], asyncio.Task[ReadinessReport]] = field(
        default_factory=dict
    )
    cancelling: set[asyncio.Task[ReadinessReport]] = field(default_factory=set)
    initialized: set[tuple[str, str]] = field(default_factory=set)


class Readiness(Plugin, provides=True, needs=(BrowserEvents,)):
    events = READINESS_EVENTS
    _state = PluginState(_State)
    _events: Inject[BrowserEvents]

    def __init__(
        self,
        options: ReadinessOptions | None = None,
        *,
        initial: ReadinessPolicy | None = None,
        ongoing: ReadinessPolicy | None = None,
    ) -> None:
        super().__init__()
        self.options = options or ReadinessOptions()
        self.initial = initial or DomReady()
        self.ongoing = ongoing or DomReady()

    async def setup(self, ctx: Context) -> None:
        ctx.effect(self._cancel)

    async def wait(
        self, tab: Tab, *, phase: ReadinessPhase = ReadinessPhase.OBSERVATION
    ) -> ReadinessReport:
        await tab.sync_document()
        phase = ReadinessPhase(phase)
        document = (tab.id, tab.document_id)
        stage = (
            ReadinessStage.ONGOING
            if document in self._state.initialized
            else ReadinessStage.INITIAL
        )
        key = (*document, phase, stage)
        if key not in self._state.pending:
            task = asyncio.create_task(self._wait(tab, phase, stage), name="browserrig:readiness")
            self._state.pending[key] = task

            def finished(completed: asyncio.Task[ReadinessReport]) -> None:
                self._state.cancelling.discard(completed)
                if self._state.pending.get(key) is completed:
                    self._state.pending.pop(key, None)
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(finished)
        return await asyncio.shield(self._state.pending[key])

    def invalidate(self, tab: Tab) -> None:
        """Invalidate this document after an application-level reset (for example in an SPA)."""
        self._state.initialized.discard((tab.id, tab.document_id))
        for key, task in tuple(self._state.pending.items()):
            if key[:2] == (tab.id, tab.document_id):
                self._state.cancelling.add(task)
                task.cancel()
                self._state.pending.pop(key, None)

    async def _cancel(self) -> None:
        tasks = tuple(set(self._state.pending.values()) | self._state.cancelling)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._state.pending.clear()
        self._state.cancelling.clear()

    @hook(AgentControlChangedEvent)
    async def _on_control(self, event: AgentControlChangedEvent) -> None:
        if event.state in (ControlState.ABORTING, ControlState.STOPPED):
            await self._cancel()

    async def _wait(
        self, tab: Tab, phase: ReadinessPhase, stage: ReadinessStage
    ) -> ReadinessReport:
        document = (tab.id, tab.document_id)
        report = await wait_for_page(
            tab,
            events=self._events,
            options=self.options,
            phase=phase,
            policy=self.initial if stage == ReadinessStage.INITIAL else self.ongoing,
            stage=stage,
        )
        if (tab.id, tab.document_id) != document:
            # Select again for the new document; do not mark it ready using the old readiness probe.
            return await self.wait(tab, phase=phase)
        if stage == ReadinessStage.INITIAL and report.status == ReadinessStatus.READY:
            # Keep only the live generation for this tab.
            self._state.initialized = {key for key in self._state.initialized if key[0] != tab.id}
            self._state.initialized.add(document)
        return report
