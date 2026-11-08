import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from time import monotonic
from uuid import uuid4

from cdpify import CDPCommandError
from harnessed.hooks import Next

from browserrig.browser import BrowserEvents, Tab
from browserrig.core import (
    BrowserError,
    ReadinessError,
    ReadinessPhase,
    ReadinessStage,
    ReadinessStatus,
    record,
    traced,
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
    record(phase=phase, stage=stage, budget=options.timeout)
    runner = _Runner(
        tab,
        options,
        phase,
        stage,
        policy,
        select,
        check,
        started if since is None else since,
    )
    timed_out = False
    try:
        timeout = asyncio.timeout(options.timeout)
        try:
            async with timeout:
                # Deliver an already-exhausted budget before sending another command.
                if options.timeout <= 0:
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
                duration=monotonic() - started,
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
                duration=monotonic() - started,
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
        duration=monotonic() - started,
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
            duration=report.duration,
            reason=report.reason,
            timed_out=report.timed_out,
        )
    )
    if status == ReadinessStatus.FAILED:
        raise ReadinessError(f"Page readiness timed out: {report.reason}")
    return report


@dataclass
class _Runner:
    tab: Tab
    options: ReadinessOptions
    phase: ReadinessPhase
    stage: ReadinessStage
    policy: ReadinessPolicy | None
    select: PolicySelector | None
    middleware: ReadinessMiddleware | None
    since: float
    strategy: ReadinessStrategy | None = None
    reason: str = "The document could not be inspected yet"
    polls: int = 0
    probe_seconds: float = 0

    async def run(self, timeout: asyncio.Timeout, document: str) -> ReadinessStatus:
        context: ReadinessContext | None = None
        while True:
            if self.tab.dialog:
                self.reason = "A JavaScript dialog must be handled first"
                return ReadinessStatus.BLOCKED
            await self.tab.sync_document()
            if self.strategy is None or document != self.tab.document_id:
                if document != self.tab.document_id:
                    self.stage = ReadinessStage.INITIAL
                document = self.tab.document_id
                deadline = timeout.when()
                assert deadline is not None
                context = ReadinessContext(
                    self.tab,
                    self.phase,
                    self.stage,
                    self.options,
                    deadline,
                    self.since,
                )
                policy = self.policy if self.policy is not None else DomReady()
                if self.select:
                    policy = await self.select(context)
                self.strategy = policy.create(context)
                # A custom probe may shorten the budget. No redirect can extend it.
                deadline = min(context.deadline, monotonic() + self.strategy.budget)
                timeout.reschedule(deadline)
                context = replace(context, deadline=deadline)
            assert self.strategy is not None
            assert context is not None
            if self.tab.navigation_pending:
                self.reason = "A navigation is still in progress"
                await asyncio.sleep(self.strategy.delay)
                continue
            probed = monotonic()
            result = (
                await self.middleware(context, self._probe)
                if self.middleware
                else await self._probe()
            )
            self.polls += 1
            self.probe_seconds += monotonic() - probed
            self.reason = result.reason or self.strategy.reason
            await self.tab.sync_document()
            if self.tab.document_id != document:
                continue
            if self.tab.navigation_pending:
                self.reason = "A navigation is still in progress"
            elif result.ready:
                return ReadinessStatus.READY
            await asyncio.sleep(self.strategy.delay)

    def timeout_status(self) -> ReadinessStatus:
        if self.strategy is not None:
            return self.strategy.timeout_status()
        return (
            ReadinessStatus.DEGRADED
            if self.options.allow_degraded_dom
            else ReadinessStatus.FAILED
        )

    async def _probe(self) -> ReadinessCheck:
        assert self.strategy is not None
        ready = await _check(self.strategy)
        return ReadinessCheck(ready=ready, reason=self.strategy.reason)


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
