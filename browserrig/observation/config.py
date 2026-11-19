from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from .retention import ImageRetention, TrimInBatches


class ScreenshotTrigger(StrEnum):
    EACH_STEP = "each_step"
    ON_REQUEST = "on_request"


type TextMode = Literal["delta", "full"]


@dataclass(frozen=True, slots=True)
class ScreenshotPolicy:
    """When screenshots are captured and how many stay in the request."""

    trigger: ScreenshotTrigger = ScreenshotTrigger.ON_REQUEST
    skip_unchanged: bool = True
    retention: ImageRetention = field(default_factory=TrimInBatches)
