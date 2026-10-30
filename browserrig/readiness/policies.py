from dataclasses import dataclass, field
from typing import Protocol

from browserrig.browser.tab import Tab
from browserrig.core.geometry import Geometry
from browserrig.core.kinds import ReadinessPhase, ReadinessStage
from browserrig.core.modes import CanvasMode

from .canvas import CanvasReadiness
from .config import ReadinessOptions
from .dom import DomReadiness
from .strategy import ReadinessStrategy


@dataclass(frozen=True)
class ReadinessContext:
    tab: Tab
    phase: ReadinessPhase
    stage: ReadinessStage
    options: ReadinessOptions
    geometry_cache: dict[tuple[str, str], Geometry]


class ReadinessPolicy(Protocol):
    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        """Create a fresh probe for this wait. Never share mutable probe state."""
        ...


@dataclass(frozen=True)
class DomReady:
    options: ReadinessOptions | None = None

    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        phase = ReadinessPhase.INITIAL if context.stage == ReadinessStage.INITIAL else context.phase
        return DomReadiness(context.tab, self.options or context.options, phase)


@dataclass(frozen=True)
class CanvasReady:
    selector: str = "canvas"
    loading_selector: str = '[role="progressbar"], [aria-busy="true"]'
    min_color_fraction: float = 0.002
    options: ReadinessOptions | None = None

    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        options = self.options or context.options
        mode = CanvasMode(
            selector=self.selector,
            loading_selector=self.loading_selector,
            min_color_fraction=self.min_color_fraction,
        )
        strategy = CanvasReadiness(context.tab, options, mode, context.geometry_cache)
        strategy.budget = (
            options.canvas_timeout if context.stage == ReadinessStage.INITIAL else options.timeout
        )
        return strategy


@dataclass(frozen=True)
class DocumentReadiness:
    """Use a separate policy for downloaded document previews, including initial waits."""

    default: ReadinessPolicy
    files: ReadinessPolicy = field(default_factory=DomReady)

    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        policy = self.files if context.tab.url.startswith("file:") else self.default
        return policy.create(context)
