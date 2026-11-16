from enum import StrEnum

from browserrig.core import Options


class ScreenshotTrigger(StrEnum):
    EACH_STEP = "each_step"
    ON_REQUEST = "on_request"


class PageText(StrEnum):
    """Which visible prose observations carry beside the controls."""

    INLINE = "inline"
    SPARSE = "sparse"
    OFF = "off"


class Screenshots(Options):
    trigger: ScreenshotTrigger = ScreenshotTrigger.ON_REQUEST
