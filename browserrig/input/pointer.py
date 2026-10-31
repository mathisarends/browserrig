import math
from dataclasses import dataclass

from browserrig.core.geometry import Point

_FRAME_INTERVAL_SECONDS = 1 / 60


def ease(progress: float) -> float:
    return 4 * progress**3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2


@dataclass(frozen=True, slots=True)
class CursorPath:
    start: Point
    end: Point
    duration: float

    @property
    def control_points(self) -> tuple[tuple[float, float], tuple[float, float]]:
        dx, dy = self.end.x - self.start.x, self.end.y - self.start.y

        def bounded(x: float, y: float) -> tuple[float, float]:
            return (
                max(
                    min(self.start.x, self.end.x), min(max(self.start.x, self.end.x), x)
                ),
                max(
                    min(self.start.y, self.end.y), min(max(self.start.y, self.end.y), y)
                ),
            )

        return (
            bounded(
                self.start.x + dx * 0.3 - dy * 0.06, self.start.y + dy * 0.3 + dx * 0.06
            ),
            bounded(
                self.start.x + dx * 0.7 - dy * 0.04, self.start.y + dy * 0.7 + dx * 0.04
            ),
        )

    @property
    def steps(self) -> int:
        return max(1, math.ceil(self.duration / _FRAME_INTERVAL_SECONDS))

    def point(self, progress: float) -> Point:
        t = ease(progress)
        u = 1 - t
        cp1, cp2 = self.control_points
        return Point(
            x=u**3 * self.start.x
            + 3 * u**2 * t * cp1[0]
            + 3 * u * t**2 * cp2[0]
            + t**3 * self.end.x,
            y=u**3 * self.start.y
            + 3 * u**2 * t * cp1[1]
            + 3 * u * t**2 * cp2[1]
            + t**3 * self.end.y,
        )


def movement(start: Point, end: Point) -> CursorPath:
    distance = math.hypot(end.x - start.x, end.y - start.y)
    duration = min(0.6, max(0.08, 0.05 + 0.075 * math.log2(distance / 20 + 1)))
    return CursorPath(start, end, duration if distance >= 2 else 0)
