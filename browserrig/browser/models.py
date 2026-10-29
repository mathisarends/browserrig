from enum import StrEnum

from pydantic import Field

from .config import Options


class Point(Options):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class ElementPoint(Point):
    scrolled: bool = False


class Geometry(Options):
    x: float = Field(default=0, ge=0)
    y: float = Field(default=0, ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    scale: float = Field(default=1, gt=0)

    def point(self, x: float, y: float) -> tuple[float, float]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("Point is outside the observed image")
        return self.x + x / self.scale, self.y + y / self.scale


class TabInfo(Options):
    id: str
    url: str
    title: str
    active: bool = False


class DownloadState(StrEnum):
    IN_PROGRESS = "inProgress"
    COMPLETED = "completed"
    CANCELED = "canceled"


class Download(Options):
    id: str
    filename: str
    url: str
    state: DownloadState = DownloadState.IN_PROGRESS
    received_bytes: int = 0
    path: str | None = None
