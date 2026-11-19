from dataclasses import dataclass

from browserrig.core import Point, Region
from browserrig.readiness import ReadinessReport


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    """One observation's needs, shared by its page model and frame source.

    `region` crops the image to a viewport area, magnified by `zoom`.
    `cursor` is where the mouse rests, in viewport CSS pixels.
    """

    report: ReadinessReport
    screenshots: bool = False
    region: Region | None = None
    zoom: float = 1
    cursor: Point | None = None
