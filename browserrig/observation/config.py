from dataclasses import dataclass, field
from enum import StrEnum

from browserrig.core import Options

from .retention import ImageRetention, TrimInBatches


class ScreenshotTrigger(StrEnum):
    EACH_STEP = "each_step"
    ON_REQUEST = "on_request"


class PageText(StrEnum):
    """Which visible prose observations carry beside the controls."""

    INLINE = "inline"
    SPARSE = "sparse"
    OFF = "off"


class DomTextMode(StrEnum):
    """Select how much DOM text to deliver at each step."""

    DELTA = "delta"
    FULL = "full"


class DomText(Options):
    """Publish complete DOM observations or deltas against a retained observation."""

    mode: DomTextMode = DomTextMode.DELTA


@dataclass(frozen=True, slots=True)
class SetOfMarks:
    """Label screenshot targets with their observation references."""


@dataclass(frozen=True, slots=True)
class Screenshots:
    """Configure screenshot timing, presentation and history."""

    trigger: ScreenshotTrigger = ScreenshotTrigger.ON_REQUEST
    marks: SetOfMarks | None = None
    cursor: bool = False
    skip_unchanged: bool = True
    retention: ImageRetention = field(default_factory=TrimInBatches)
