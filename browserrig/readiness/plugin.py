import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from harnessed import Context, Inject, Plugin, PluginState, hook
from harnessed.events import AgentControlChangedEvent, ControlState
from harnessed.hooks import Next

from browserrig.browser import BrowserEvents, Tab
from browserrig.core import (
    ReadinessError,
    ReadinessPhase,
    ReadinessStage,
    ReadinessStatus,
)
from browserrig.events import (
    READINESS_EVENTS,
)

from .config import ReadinessOptions
from .hooks import CheckReadiness, ReadinessCheck, SelectReadiness
from .models import ReadinessReport
from .policies import DomReady, ReadinessContext, ReadinessPolicy
from .wait import wait_for_page


@dataclass
class _State:
    pending: dict[tuple[str, ...], asyncio.Task[ReadinessReport]] = field(
        default_factory=dict
    )
    cancelling: set[asyncio.Task[ReadinessReport]] = field(default_factory=set)
    initialized: set[tuple[str, str]] = field(default_factory=set)
    deferred: dict[str, ReadinessReport] = field(default_factory=dict)
    spent: dict[str, float] = field(default_factory=dict)
    context: Context | None = None


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
        self.initial = initial if initial is not None else DomReady()
        self.ongoing = ongoing if ongoing is not None else DomReady()

    async def setup(self, ctx: Context) -> None:
        self._state.context = ctx
        ctx.effect(self._cancel)

    async def wait(
        self,
        tab: Tab,
        *,
        phase: ReadinessPhase = ReadinessPhase.OBSERVATION,
        dispatch: Callable[[], Awaitable[None]] | None = None,
    ) -> ReadinessReport:
        phase = ReadinessPhase(phase)
        if report := self._state.deferred.get(tab.id):
            if dispatch is not None:
                raise ReadinessError(
                    report.reason
                    + "; inspect the next observation before navigating again"
                )
            if phase == ReadinessPhase.OBSERVATION:
                self._state.deferred.pop(tab.id, None)
                self._state.spent.pop(tab.id, None)
            return report.model_copy(
                update={"phase": phase, "document_id": tab.document_id}
            )
        document = (tab.id, tab.document_id)
        stage = (
            ReadinessStage.ONGOING
            if document in self._state.initialized
            else ReadinessStage.INITIAL
        )
        # Read-only waiters share probes. A command must always execute independently.
        key = (*document, phase, stage, uuid4().hex if dispatch is not None else "")
        if key not in self._state.pending:
            task = asyncio.create_task(
                self._wait(tab, phase, stage, dispatch), name="browserrig:readiness"
            )
            self._state.pending[key] = task

            def finished(completed: asyncio.Task[ReadinessReport]) -> None:
                self._state.cancelling.discard(completed)
                if self._state.pending.get(key) is completed:
                    self._state.pending.pop(key, None)
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(finished)
        task = self._state.pending[key]
        return await task if dispatch is not None else await asyncio.shield(task)

    def invalidate(self, tab: Tab) -> None:
        """Invalidate this document after an application-level reset (for example in an SPA)."""
        self._state.initialized.discard((tab.id, tab.document_id))
        self._state.deferred.pop(tab.id, None)
        self._state.spent.pop(tab.id, None)
        for key, task in tuple(self._state.pending.items()):
            if key[0] == tab.id:
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
        self._state.deferred.clear()
        self._state.spent.clear()

    @hook(AgentControlChangedEvent)
    async def _on_control(self, event: AgentControlChangedEvent) -> None:
        if event.state in (ControlState.ABORTING, ControlState.STOPPED):
            await self._cancel()

    async def _wait(
        self,
        tab: Tab,
        phase: ReadinessPhase,
        stage: ReadinessStage,
        dispatch: Callable[[], Awaitable[None]] | None,
    ) -> ReadinessReport:
        remaining = max(0, self.options.timeout - self._state.spent.get(tab.id, 0))
        report = await wait_for_page(
            tab,
            events=self._events,
            options=self.options.model_copy(update={"timeout": remaining}),
            phase=phase,
            stage=stage,
            select=self._select,
            check=self._check,
            dispatch=dispatch,
        )
        self._state.spent[tab.id] = self._state.spent.get(tab.id, 0) + report.duration
        if phase == ReadinessPhase.OBSERVATION:
            self._state.spent.pop(tab.id, None)
        elif report.timed_out:
            # The observation following a slow action must reach the model without
            # another full wait. It consumes this receipt; the next action can retry.
            self._state.deferred[tab.id] = report
        if (
            report.stage == ReadinessStage.INITIAL
            and report.status == ReadinessStatus.READY
        ):
            # Keep only the live generation for this tab.
            self._state.initialized = {
                key for key in self._state.initialized if key[0] != tab.id
            }
            self._state.initialized.add((tab.id, report.document_id))
        return report

    async def _select(self, context: ReadinessContext) -> ReadinessPolicy:
        assert self._state.context is not None
        selected = await self._state.context.dispatch(SelectReadiness(context))
        if selected is not None:
            return selected
        return self.initial if context.stage == ReadinessStage.INITIAL else self.ongoing

    async def _check(
        self, context: ReadinessContext, next_: Next[ReadinessCheck]
    ) -> ReadinessCheck:
        assert self._state.context is not None
        return await self._state.context.dispatch(
            CheckReadiness(context), default=next_
        )
