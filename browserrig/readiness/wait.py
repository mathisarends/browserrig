import asyncio
from time import monotonic
from typing import assert_never
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import BrowserEvents
from browserrig.browser.tab import Tab
from browserrig.core.errors import ReadinessError
from browserrig.core.geometry import Geometry
from browserrig.core.kinds import ReadinessPhase, ReadinessStage, ReadinessStatus
from browserrig.core.modes import CanvasMode, DomMode, ObservationMode
from browserrig.events import (
    BrowserEvent,
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)

from .canvas import CanvasReadiness
from .config import ReadinessOptions
from .dom import DomReadiness
from .models import ReadinessReport
from .policies import ReadinessContext, ReadinessPolicy
from .strategy import ReadinessStrategy


async def wait_for_page(
    tab: Tab,
    *,
    events: BrowserEvents | None = None,
    mode: ObservationMode | None = None,
    options: ReadinessOptions | None = None,
    phase: ReadinessPhase = ReadinessPhase.INITIAL,
    geometry_cache: dict[tuple[str, str], Geometry] | None = None,
    policy: ReadinessPolicy | None = None,
    stage: ReadinessStage | None = None,
) -> ReadinessReport:
    emit = events.emit if events is not None else _discard
    selected = mode or DomMode()
    options = options or ReadinessOptions()
    if geometry_cache is None:
        geometry_cache = {}
    await tab.sync_document()
    started_document = tab.document_id
    started = monotonic()
    rid = uuid4().hex
    stage = stage or (
        ReadinessStage.INITIAL if phase == ReadinessPhase.INITIAL else ReadinessStage.ONGOING
    )
    await emit(
        ReadinessStartedEvent(
            readiness_id=rid,
            target_id=tab.id,
            document_id=started_document,
            mode=selected.kind,
            phase=phase,
            stage=stage,
        )
    )
    status = ReadinessStatus.READY
    try:
        strategy = (
            policy.create(ReadinessContext(tab, phase, stage, options, geometry_cache))
            if policy
            else _readiness_strategy(selected, tab, options, phase, geometry_cache)
        )
        status = await _poll(tab, strategy, started_document, reselect=policy is not None)
    except asyncio.CancelledError:
        await emit(
            ReadinessCancelledEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=started_document,
                mode=selected.kind,
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
                mode=selected.kind,
                phase=phase,
                stage=stage,
                duration=monotonic() - started,
                reason=type(error).__name__,
            )
        )
        raise ReadinessError(f"Readiness probe failed ({type(error).__name__})") from error
    report = ReadinessReport(
        id=rid,
        target_id=tab.id,
        document_id=tab.document_id,
        mode=selected.kind,
        phase=phase,
        stage=stage,
        status=status,
        duration=monotonic() - started,
        reason=strategy.reason if status != ReadinessStatus.READY else "",
        geometry=strategy.geometry,
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
            mode=selected.kind,
            phase=phase,
            stage=stage,
            duration=report.duration,
            reason=report.reason,
        )
    )
    if status == ReadinessStatus.FAILED:
        raise ReadinessError(f"{selected.kind} readiness timed out: {strategy.reason}")
    return report


async def _poll(
    tab: Tab, strategy: ReadinessStrategy, document_id: str, *, reselect: bool
) -> ReadinessStatus:
    try:
        async with asyncio.timeout(strategy.budget):
            while True:
                if tab.dialog:
                    strategy.reason = "A JavaScript dialog must be handled first"
                    return ReadinessStatus.BLOCKED
                ready = await _check(strategy)
                await tab.sync_document()
                if reselect and tab.document_id != document_id:
                    strategy.reason = "document changed during readiness; select policy again"
                    return ReadinessStatus.DEGRADED
                if ready:
                    return ReadinessStatus.READY
                await asyncio.sleep(strategy.delay)
    except TimeoutError:
        return strategy.timeout_status()


async def _discard(_event: BrowserEvent) -> None:
    pass


def _readiness_strategy(
    mode: ObservationMode,
    tab: Tab,
    options: ReadinessOptions,
    phase: ReadinessPhase,
    geometry_cache: dict[tuple[str, str], Geometry],
) -> ReadinessStrategy:
    # File previews use the full viewport, even when the task tab is a canvas application.
    if tab.url.startswith("file:"):
        return DomReadiness(tab, options, phase)
    match mode:
        case DomMode():
            return DomReadiness(tab, options, phase)
        case CanvasMode():
            return CanvasReadiness(tab, options, mode, geometry_cache)
        case _:
            assert_never(mode)


async def _check(strategy: ReadinessStrategy) -> bool:
    try:
        return await strategy.check()
    except CDPCommandError as error:
        if not any(text in error.message.lower() for text in ("context", "frame", "navigat")):
            raise
        strategy.reason = "document changed during readiness"
        return False
