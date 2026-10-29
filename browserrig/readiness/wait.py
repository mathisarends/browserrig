import asyncio
from time import monotonic
from typing import assert_never
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.tab import Tab
from browserrig.core.errors import ReadinessError
from browserrig.core.geometry import Geometry
from browserrig.core.modes import CanvasMode, DomMode, ObservationMode
from browserrig.events import (
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)

from .canvas import CanvasReadiness
from .config import ReadinessOptions
from .dom import DomReadiness
from .models import ReadinessPhase, ReadinessReport, ReadinessStatus
from .strategy import ReadinessStrategy


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


async def wait_for_page(
    browser: Browser,
    tab: Tab,
    *,
    mode: ObservationMode | None = None,
    options: ReadinessOptions | None = None,
    phase: ReadinessPhase = ReadinessPhase.INITIAL,
    geometry_cache: dict[tuple[str, str], Geometry] | None = None,
) -> ReadinessReport:
    selected = mode or DomMode()
    options = options or ReadinessOptions()
    if geometry_cache is None:
        geometry_cache = {}
    await tab.sync_document()
    started_document = tab.document_id
    started = monotonic()
    rid = uuid4().hex
    strategy = _readiness_strategy(selected, tab, options, phase, geometry_cache)
    await browser.emit(
        ReadinessStartedEvent(
            readiness_id=rid,
            target_id=tab.id,
            document_id=started_document,
            mode=selected.kind,
            phase=phase,
        )
    )
    status = ReadinessStatus.READY
    try:
        async with asyncio.timeout(strategy.budget):
            while True:
                if tab.dialog:
                    status = ReadinessStatus.BLOCKED
                    strategy.reason = "A JavaScript dialog must be handled first"
                    break
                if await _check(strategy):
                    break
                await asyncio.sleep(strategy.delay)
    except TimeoutError:
        status = strategy.timeout_status()
    except asyncio.CancelledError:
        await browser.emit(
            ReadinessCancelledEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=started_document,
                mode=selected.kind,
                phase=phase,
                duration=monotonic() - started,
                reason="cancelled",
            )
        )
        raise
    except Exception as error:
        await browser.emit(
            ReadinessFailedEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=started_document,
                mode=selected.kind,
                phase=phase,
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
    await browser.emit(
        event_type(
            readiness_id=rid,
            target_id=tab.id,
            document_id=started_document,
            mode=selected.kind,
            phase=phase,
            duration=report.duration,
            reason=report.reason,
        )
    )
    if status == ReadinessStatus.FAILED:
        raise ReadinessError(f"{selected.kind} readiness timed out: {strategy.reason}")
    return report


async def _check(strategy: ReadinessStrategy) -> bool:
    try:
        return await strategy.check()
    except CDPCommandError as error:
        if not any(text in error.message.lower() for text in ("context", "frame", "navigat")):
            raise
        strategy.reason = "document changed during readiness"
        return False
