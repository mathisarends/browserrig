from typing import Literal, Self

from pydantic import Field, model_validator

from browserrig.activity.models import TimeRange
from browserrig.browser.config import Options
from browserrig.browser.models import Geometry
from browserrig.events import ActivityFinishedEvent


class RecordingSegment(Options):
    id: str
    path: str
    mime: str
    target_id: str
    started_at: float
    ended_at: float
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(gt=0)
    geometry: Geometry | None = None

    @model_validator(mode="after")
    def _ordered_interval(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("Recording segment end precedes start")
        return self


class RecordingManifest(Options):
    version: Literal[1] = 1
    browser_id: str
    segments: tuple[RecordingSegment, ...]
    failed: bool
    activity: tuple[ActivityFinishedEvent, ...] = ()
    inference_only: tuple[TimeRange, ...] = ()
