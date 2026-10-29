import asyncio
from dataclasses import dataclass
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
from .dom import DOMProbe, probe_dom
from .figma import locate_prototype, probe_figma
from .models import ReadinessPhase, ReadinessReport, ReadinessStatus


@dataclass
class _Probe:
    tab: Tab
    mode: ObservationMode
    options: ReadinessOptions
    phase: ReadinessPhase
    started: float
    geometry_cache: dict[tuple[str, str], Geometry]
    geometry: Geometry | None
    last_geometry: Geometry | None = None
    usable: bool = False
    reason: str = ""
    delay: float = 0

    async def check(self) -> bool:
        canvas = isinstance(self.mode, FigmaMode)
        self.delay = max(self.options.poll_interval, 0.5 if canvas else 0)
        try:
            state = await probe_dom(self.tab)
            self.usable = state.loaded and state.body
            if isinstance(self.mode, FigmaMode):
                return await self._canvas(state, self.mode)
            minimum = (
                self.options.navigation_min_ms
                if self.phase in {ReadinessPhase.INITIAL, ReadinessPhase.NAVIGATION}
                else 0
            )
            self.reason = "DOM is loading or continues changing"
            return (
                self.usable
                and state.quiet_ms >= self.options.quiet_ms
                and (monotonic() - self.started) * 1000 >= minimum
            )
        except CDPCommandError as error:
            if not any(text in error.message.lower() for text in ("context", "frame", "navigat")):
                raise
            self.reason = "document changed during readiness"
            return False

    async def _canvas(self, state: DOMProbe, mode: FigmaMode) -> bool:
        if self.geometry is not None:
            location = await locate_prototype(self.tab, mode)
            if location.geometry == self.geometry:
                # Recheck pixels only when capture geometry changes.
                self.delay = self.options.poll_interval
                return state.quiet_ms >= self.options.quiet_ms
            self.geometry = None
            self.geometry_cache.pop((self.tab.id, self.tab.document_id), None)
        candidate, self.reason = await probe_figma(self.tab, mode)
        if candidate is not None and candidate == self.last_geometry:
            self.geometry = candidate
            self.geometry_cache[(self.tab.id, self.tab.document_id)] = candidate
            return True
        self.last_geometry = candidate
        self.reason = self.reason or "canvas geometry is not stable yet"
        return False


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
    probe = _Probe(tab, selected, options, phase, started, geometry_cache, geometry_cache.get(key))
    try:
        async with asyncio.timeout(budget):
            while True:
                if tab.dialog:
                    status = ReadinessStatus.BLOCKED
                    probe.reason = "A JavaScript dialog must be handled first"
                    break
                if await probe.check():
                    break
                await asyncio.sleep(probe.delay)
    except TimeoutError:
        status = (
            ReadinessStatus.DEGRADED
            if not canvas and probe.usable and options.allow_degraded_dom
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
        reason=probe.reason if status != ReadinessStatus.READY else "",
        geometry=probe.geometry,
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
        raise ReadinessError(f"{selected.kind} readiness timed out: {probe.reason}")
    return report
