import asyncio
from dataclasses import dataclass, field

from harnessed import Context, Inject, Plugin, PluginState, hook
from harnessed.events import AgentControlChangedEvent, ControlState

from browserrig.browser.base import Browser
from browserrig.browser.models import Geometry
from browserrig.browser.tab import Tab
from browserrig.events import (
    READINESS_EVENTS,
)
from browserrig.observation.config import DomMode, ObservationMode

from .config import ReadinessOptions
from .models import ReadinessPhase, ReadinessReport
from .wait import wait_for_page


@dataclass
class _State:
    pending: dict[tuple[str, str, str], asyncio.Task[ReadinessReport]] = field(default_factory=dict)
    geometry: dict[tuple[str, str], Geometry] = field(default_factory=dict)


class Readiness(Plugin, provides=True, needs=(Browser,)):
    events = READINESS_EVENTS
    _state = PluginState(_State)
    _browser: Inject[Browser]

    def __init__(
        self, mode: ObservationMode | None = None, options: ReadinessOptions | None = None
    ) -> None:
        super().__init__()
        self.mode = mode or DomMode()
        self.options = options or ReadinessOptions()

    async def setup(self, ctx: Context) -> None:
        ctx.effect(self._cancel)

    async def _cancel(self) -> None:
        tasks = tuple(self._state.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._state.pending.clear()

    @hook(AgentControlChangedEvent)
    async def _on_control(self, event: AgentControlChangedEvent) -> None:
        if event.state in (ControlState.ABORTING, ControlState.STOPPED):
            await self._cancel()

    async def wait(
        self, tab: Tab, *, phase: ReadinessPhase = ReadinessPhase.OBSERVATION
    ) -> ReadinessReport:
        await tab.main_frame()
        key = (tab.id, tab.document_id, phase)
        if key not in self._state.pending:
            task = asyncio.create_task(self._wait(tab, phase), name="browserrig:readiness")
            self._state.pending[key] = task

            def finished(completed: asyncio.Task[ReadinessReport]) -> None:
                self._state.pending.pop(key, None)
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(finished)
        return await asyncio.shield(self._state.pending[key])

    async def _wait(self, tab: Tab, phase: ReadinessPhase) -> ReadinessReport:
        return await wait_for_page(
            self._browser,
            tab,
            mode=self.mode,
            options=self.options,
            phase=phase,
            geometry_cache=self._state.geometry,
        )
