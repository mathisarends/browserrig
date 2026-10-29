from importlib.resources import files
from time import monotonic

from browserrig.browser.config import Options
from browserrig.browser.tab import Tab
from browserrig.kinds import ReadinessPhase, ReadinessStatus

from .config import ReadinessOptions
from .strategy import ReadinessStrategy

SCRIPT = files("browserrig.readiness").joinpath("scripts/dom.js").read_text(encoding="utf-8")


class DOMProbe(Options):
    loaded: bool
    body: bool
    quiet_ms: float
    width: float
    height: float


async def probe_dom(tab: Tab) -> DOMProbe:
    return DOMProbe.model_validate(await tab.evaluate(SCRIPT))


class DomReadiness(ReadinessStrategy):
    def __init__(self, tab: Tab, options: ReadinessOptions, phase: ReadinessPhase) -> None:
        super().__init__(tab, options)
        self.budget = options.timeout
        self.usable = False
        navigating = phase in {ReadinessPhase.INITIAL, ReadinessPhase.NAVIGATION}
        minimum = options.navigation_min_ms / 1000 if navigating else 0
        self.earliest = monotonic() + minimum

    async def check(self) -> bool:
        state = await probe_dom(self.tab)
        self.usable = state.loaded and state.body
        self.reason = "DOM is loading or continues changing"
        return (
            self.usable and state.quiet_ms >= self.options.quiet_ms and monotonic() >= self.earliest
        )

    def timeout_status(self) -> ReadinessStatus:
        if self.usable and self.options.allow_degraded_dom:
            return ReadinessStatus.DEGRADED
        return ReadinessStatus.FAILED
