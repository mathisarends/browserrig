import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial
from time import monotonic
from uuid import uuid4

from cdpify import CDPCommandError
from harnessed.hooks import Next
from harnessed.tracing import record, traced

from browserrig.browser import AppState, BrowserEvents, Tab, blocked_reason
from browserrig.core import (
    BrowserError,
    ReadinessError,
    ReadinessPhase,
    ReadinessStage,
    ReadinessStatus,
)
from browserrig.events import (
    BrowserEvent,
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)

from .config import ReadinessOptions
from .hooks import ReadinessCheck
from .models import ReadinessReport
from .policies import DomReady, ReadinessContext, ReadinessPolicy
from .strategy import ReadinessStrategy

type PolicySelector = Callable[[ReadinessContext], Awaitable[ReadinessPolicy]]
type ReadinessMiddleware = Callable[
    [ReadinessContext, Next[ReadinessCheck]], Awaitable[ReadinessCheck]
]


@traced
async def wait_for_page(
    tab: Tab,
    *,
    events: BrowserEvents | None = None,
    options: ReadinessOptions | None = None,
    phase: ReadinessPhase = ReadinessPhase.INITIAL,
    policy: ReadinessPolicy | None = None,
    stage: ReadinessStage | None = None,
    select: PolicySelector | None = None,
    check: ReadinessMiddleware | None = None,
    dispatch: Callable[[], Awaitable[None]] | None = None,
    since: float | None = None,
    app_state: AppState | None = None,
) -> ReadinessReport:
    """Wait until `tab` is ready. `since` is when its cause began, before this wait."""
    emit = events.emit if events is not None else _discard
    options = options or ReadinessOptions()
    started_document = tab.document_id
    started = monotonic()
    rid = uuid4().hex
    stage = stage or (
        ReadinessStage.INITIAL
        if phase == ReadinessPhase.INITIAL
        else ReadinessStage.ONGOING
    )
    await emit(
        ReadinessStartedEvent(
            readiness_id=rid,
            target_id=tab.id,
            document_id=started_document,
            phase=phase,
            stage=stage,
        )
    )
    record(phase=phase, stage=stage, budget=options.timeout_seconds)
    runner = _Runner(
        tab,
        options=options,
        phase=phase,
        stage=stage,
        policy=policy,
        select=select,
        middleware=check,
        since=started if since is None else since,
        app_state=app_state,
    )
    timed_out = False
    try:
        timeout = asyncio.timeout(options.timeout_seconds)
        try:
            async with timeout:
                # Deliver an already-exhausted budget before sending another command.
                if options.timeout_seconds <= 0:
                    await asyncio.sleep(0)
                if dispatch is not None:
                    await dispatch()
                status = await runner.run(timeout, started_document)
        except TimeoutError:
            if not timeout.expired():
                raise
            timed_out = True
            status = runner.timeout_status()
            runner.reason = "Readiness budget exhausted: " + runner.reason
    except asyncio.CancelledError:
        await emit(
            ReadinessCancelledEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=started_document,
                phase=phase,
                stage=stage,
                duration_seconds=monotonic() - started,
                reason="cancelled",
            )
        )
        raise
    except Exception as error:
        await emit(
            ReadinessFailedEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=started_document,
                phase=phase,
                stage=stage,
                duration_seconds=monotonic() - started,
                reason=type(error).__name__,
            )
        )
        if isinstance(error, BrowserError):
            raise
        raise ReadinessError(
            f"Readiness probe failed ({type(error).__name__})"
        ) from error
    report = ReadinessReport(
        id=rid,
        target_id=tab.id,
        document_id=tab.document_id,
        phase=phase,
        stage=runner.stage,
        status=status,
        duration_seconds=monotonic() - started,
        reason=runner.reason if status != ReadinessStatus.READY else "",
        timed_out=timed_out,
    )
    record(
        status=status,
        timed_out=timed_out,
        reason=report.reason,
        polls=runner.polls,
        probe_ms=round(runner.probe_seconds * 1000, 1),
    )
    match status:
        case ReadinessStatus.READY:
            event_type = ReadyEvent
        case ReadinessStatus.DEGRADED | ReadinessStatus.BLOCKED:
            event_type = ReadinessDegradedEvent
        case _:
            event_type = ReadinessFailedEvent
    await emit(
        event_type(
            readiness_id=rid,
            target_id=tab.id,
            document_id=started_document,
            phase=phase,
            stage=stage,
            duration_seconds=report.duration_seconds,
            reason=report.reason,
            timed_out=report.timed_out,
        )
    )
    if status == ReadinessStatus.FAILED:
        raise ReadinessError(f"Page readiness timed out: {report.reason}")
    return report


class _Runner:
    """Own the evolving wait budget and counters for one readiness operation."""

    def __init__(
        self,
        tab: Tab,
        *,
        options: ReadinessOptions,
        phase: ReadinessPhase,
        stage: ReadinessStage,
        policy: ReadinessPolicy | None,
        select: PolicySelector | None,
        middleware: ReadinessMiddleware | None,
        since: float,
        app_state: AppState | None,
    ) -> None:
        self._tab = tab
        self._options = options
        self._phase = phase
        self._policy = policy
        self._select = select
        self._middleware = middleware
        self._since = since
        self._app_state = app_state
        self._strategy: ReadinessStrategy | None = None
        self.stage = stage
        self.reason = "The document could not be inspected yet"
        self.polls = 0
        self.probe_seconds = 0.0

    async def run(self, timeout: asyncio.Timeout, document: str) -> ReadinessStatus:
        probe: _Probe | None = None
        while True:
            if await self._is_blocked():
                return ReadinessStatus.BLOCKED
            await self._tab.sync_document()
            if probe is None or document != self._tab.document_id:
                if document != self._tab.document_id:
                    self.stage = ReadinessStage.INITIAL
                document = self._tab.document_id
                deadline = timeout.when()
                assert deadline is not None
                context = ReadinessContext(
                    self._tab,
                    self._phase,
                    self.stage,
                    self._options,
                    deadline,
                    self._since,
                )
                policy = self._policy if self._policy is not None else DomReady()
                if self._select:
                    policy = await self._select(context)
                strategy = self._strategy = policy.create(context)
                # A custom probe may shorten the budget. No redirect can extend it.
                deadline = min(context.deadline, monotonic() + strategy.budget)
                timeout.reschedule(deadline)
                probe = _Probe(replace(context, deadline=deadline), strategy)
            if self._tab.navigation_pending:
                self.reason = "A navigation is still in progress"
                await asyncio.sleep(probe.strategy.delay)
                continue
            probed = monotonic()
            result = (
                await self._middleware(probe.context, partial(_probe, probe.strategy))
                if self._middleware
                else await _probe(probe.strategy)
            )
            self.polls += 1
            self.probe_seconds += monotonic() - probed
            self.reason = result.reason or probe.strategy.reason
            await self._tab.sync_document()
            if self._tab.document_id != document:
                continue
            if self._tab.navigation_pending:
                self.reason = "A navigation is still in progress"
            elif result.ready:
                return (
                    ReadinessStatus.BLOCKED
                    if await self._is_blocked()
                    else ReadinessStatus.READY
                )
            await asyncio.sleep(probe.strategy.delay)

    def timeout_status(self) -> ReadinessStatus:
        if self._strategy is not None:
            return self._strategy.timeout_status()
        return (
            ReadinessStatus.DEGRADED
            if self._options.allow_degraded_dom
            else ReadinessStatus.FAILED
        )

    async def _is_blocked(self) -> bool:
        reason = await blocked_reason(self._tab, self._app_state)
        if reason is None:
            return False
        self.reason = reason
        return True


@dataclass(frozen=True, slots=True)
class _Probe:
    context: ReadinessContext
    strategy: ReadinessStrategy


async def _probe(strategy: ReadinessStrategy) -> ReadinessCheck:
    ready = await _check(strategy)
    return ReadinessCheck(ready=ready, reason=strategy.reason)


async def _discard(_event: BrowserEvent) -> None:
    pass


async def _check(strategy: ReadinessStrategy) -> bool:
    try:
        return await strategy.check()
    except CDPCommandError as error:
        if not any(
            text in error.message.lower() for text in ("context", "frame", "navigat")
        ):
            raise
        strategy.reason = "document changed during readiness"
        return False
