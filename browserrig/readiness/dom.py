import asyncio
from time import monotonic

from browserrig.browser.tab import Tab
from browserrig.core.kinds import ReadinessPhase, ReadinessStatus
from browserrig.scripts import STABILITY
from browserrig.scripts.models import DOMProbe

from .config import ReadinessOptions
from .strategy import ReadinessStrategy


async def probe_dom(tab: Tab) -> DOMProbe:
    main = await tab.main_frame()
    state = await main.run(STABILITY)
    if not state.unobserved_frames:
        return state
    frames = await tab.frames()
    results = await asyncio.gather(
        *(frame.run(STABILITY) for frame in frames if frame.id != main.id),
        return_exceptions=True,
    )
    children = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        children.append(result)
    return state.model_copy(
        update={
            "loaded": state.loaded and all(child.loaded for child in children),
            "quiet_ms": min([state.quiet_ms, *(child.quiet_ms for child in children)]),
            "animations": state.animations
            + sum(child.animations for child in children),
            "busy": state.busy or any(child.busy for child in children),
            "limited": state.limited
            or bool(tab.frame_limitations)
            or any(child.limited for child in children),
        }
    )


class DomReadiness(ReadinessStrategy):
    def __init__(
        self, tab: Tab, options: ReadinessOptions, phase: ReadinessPhase
    ) -> None:
        super().__init__(tab, options)
        self.budget = options.timeout
        self._started = monotonic()
        self._after_action = phase == ReadinessPhase.AFTER_ACTION
        minimum = 0
        if phase in {ReadinessPhase.INITIAL, ReadinessPhase.NAVIGATION}:
            minimum = options.navigation_min_ms
        elif self._after_action:
            minimum = options.action_min_ms
        self._earliest = self._started + minimum / 1000

    async def check(self) -> bool:
        state = await probe_dom(self._tab)
        now = monotonic()
        quiet = state.quiet_ms
        if self._after_action:
            # Quiet time before input cannot establish that its response has settled.
            quiet = min(quiet, (now - self._started) * 1000)
        self.reason = "DOM is loading or continues changing"
        if state.animations:
            self.reason = "A visible animation is still running"
        elif state.busy:
            self.reason = "The page reports visible busy content"
        elif state.limited:
            self.reason = "Some page activity could not be inspected"
        return (
            state.loaded
            and state.body
            and not (state.busy or state.limited or state.animations)
            and quiet >= self._options.quiet_ms
            and now >= self._earliest
        )

    def timeout_status(self) -> ReadinessStatus:
        if self._options.allow_degraded_dom:
            return ReadinessStatus.DEGRADED
        return ReadinessStatus.FAILED
