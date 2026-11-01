from enum import StrEnum

from browserrig.core import Options


class ScreenshotTrigger(StrEnum):
    EACH_STEP = "each_step"
    ON_REQUEST = "on_request"


class Screenshots(Options):
    trigger: ScreenshotTrigger = ScreenshotTrigger.ON_REQUEST
