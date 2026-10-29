import asyncio
from time import monotonic
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.errors import ReadinessError
from browserrig.browser.models import Geometry
from browserrig.browser.tab import Tab
from browserrig.events import (
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)
from browserrig.observation.config import FigmaMode, ObservationMode, WebMode

from .config import ReadinessOptions
from .dom import probe_dom
from .figma import locate_prototype, probe_figma
from .models import ReadinessPhase, ReadinessReport, ReadinessStatus


async def wait_for_page(
    browser: Browser,
    tab: Tab,
    *,
    mode: ObservationMode | None = None,
    options: ReadinessOptions | None = None,
    phase: ReadinessPhase = ReadinessPhase.INITIAL,
    geometry_cache: dict[tuple[str, str], Geometry] | None = None,
) -> ReadinessReport:
    """The same readiness algorithm for a direct browser and the Harnessed plugin."""
    selected = mode or WebMode()
    options = options or ReadinessOptions()
    if geometry_cache is None:
        geometry_cache = {}
    await tab.main_frame()
    started = monotonic()
    rid = uuid4().hex
    key = (tab.id, tab.document_id)
    canvas = isinstance(selected, FigmaMode)
    budget = options.figma_timeout if canvas and key not in geometry_cache else options.timeout
    await browser.emit(
        ReadinessStartedEvent(
            readiness_id=rid,
            target_id=tab.id,
            document_id=tab.document_id,
            mode=selected.kind,
            phase=phase,
        )
    )
    status = ReadinessStatus.READY
    reason = ""
    geometry = geometry_cache.get(key)
    last_geometry: Geometry | None = None
    usable = False
    try:
        async with asyncio.timeout(budget):
            while True:
                if tab.dialog:
                    status, reason = (
                        ReadinessStatus.BLOCKED,
                        "A JavaScript dialog must be handled first",
                    )
                    break
                try:
                    state = await probe_dom(tab)
                    usable = state.loaded and state.body
                    if canvas:
                        if geometry is not None:
                            location = await locate_prototype(tab, selected)
                            if location.geometry == geometry:
                                # Later loading content is observable; initial pixel readiness
                                # is repeated only when capture geometry changes.
                                if state.quiet_ms >= options.quiet_ms:
                                    break
                                await asyncio.sleep(options.poll_interval)
                                continue
                            geometry = None
                            geometry_cache.pop((tab.id, tab.document_id), None)
                        candidate, reason = await probe_figma(tab, selected)
                        if candidate is not None and candidate == last_geometry:
                            geometry = candidate
                            geometry_cache[(tab.id, tab.document_id)] = geometry
                            break
                        last_geometry = candidate
                        reason = reason or "canvas geometry is not stable yet"
                    else:
                        minimum = (
                            options.navigation_min_ms
                            if phase in {ReadinessPhase.INITIAL, ReadinessPhase.NAVIGATION}
                            else 0
                        )
                        if (
                            usable
                            and state.quiet_ms >= options.quiet_ms
                            and (monotonic() - started) * 1000 >= minimum
                        ):
                            break
                        reason = "DOM is loading or continues changing"
                except CDPCommandError as error:
                    if not any(
                        text in error.message.lower() for text in ("context", "frame", "navigat")
                    ):
                        raise
                    reason = "document changed during readiness"
                await asyncio.sleep(max(options.poll_interval, 0.5 if canvas else 0))
    except TimeoutError:
        status = (
            ReadinessStatus.DEGRADED
            if not canvas and usable and options.allow_degraded_dom
            else ReadinessStatus.FAILED
        )
    except asyncio.CancelledError:
        await browser.emit(
            ReadinessCancelledEvent(
                readiness_id=rid,
                target_id=tab.id,
                document_id=tab.document_id,
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
                document_id=tab.document_id,
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
        reason=reason if status != ReadinessStatus.READY else "",
        geometry=geometry,
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
            document_id=tab.document_id,
            mode=selected.kind,
            phase=phase,
            duration=report.duration,
            reason=report.reason,
        )
    )
    if status == ReadinessStatus.FAILED:
        raise ReadinessError(f"{selected.kind} readiness timed out: {reason}")
    return report
