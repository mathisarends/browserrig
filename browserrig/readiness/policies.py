from dataclasses import dataclass
from time import monotonic
from typing import Protocol, override

from browserrig.browser import Tab
from browserrig.core import ReadinessPhase, ReadinessStage, ReadinessStatus

from .config import ReadinessOptions
from .dom import DomReadiness
from .strategy import ReadinessStrategy


@dataclass(frozen=True)
class ReadinessContext:
    tab: Tab
    phase: ReadinessPhase
    stage: ReadinessStage
    options: ReadinessOptions
    deadline: float = float("inf")
    # When the cause of this wait began, such as an action's input; None is the wait itself.
    since: float | None = None

    @property
    def remaining(self) -> float:
        """Time left in the shared wait, including redirects and extension hooks."""
        return max(0, self.deadline - monotonic())


class ReadinessPolicy(Protocol):
    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        """Create a fresh probe for this wait. Never share mutable probe state."""
        ...


@dataclass(frozen=True)
class DomReady:
    options: ReadinessOptions | None = None

    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        phase = (
            ReadinessPhase.INITIAL
            if context.stage == ReadinessStage.INITIAL
            else context.phase
        )
        return DomReadiness(context.tab, self.options or context.options, phase)


class BrowserReady(ReadinessPolicy):
    """Use browser load events without running a script in the page."""

    @override
    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        return _BrowserLoad(context.tab, context.options)


class _BrowserLoad(ReadinessStrategy):
    def __init__(self, tab: Tab, options: ReadinessOptions) -> None:
        super().__init__(tab, options)
        self.budget = options.timeout_seconds

    async def check(self) -> bool:
        self.reason = "The browser is still loading the page"
        return not self._tab.loading

    def timeout_status(self) -> ReadinessStatus:
        if self._options.allow_degraded_dom:
            return ReadinessStatus.DEGRADED
        return ReadinessStatus.FAILED
