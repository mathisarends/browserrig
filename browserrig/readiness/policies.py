from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from browserrig.browser import Tab
from browserrig.core.kinds import ReadinessPhase, ReadinessStage

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
