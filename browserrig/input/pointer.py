import math
from dataclasses import dataclass
from typing import Self

from browserrig.core import Point

type ControlPoint = tuple[float, float]

_FRAME_INTERVAL_SECONDS = 1 / 60


@dataclass(frozen=True, slots=True)
class CursorPath:
    """One eased cubic Bézier stroke of the pointer, taking `duration` seconds."""

    start: Point
    end: Point
    duration: float
    control_points: tuple[ControlPoint, ControlPoint]

    @classmethod
    def curved(
        cls,
        start: Point,
        end: Point,
        duration: float,
        *,
        bend: tuple[float, float] = (0.06, 0.04),
    ) -> Self:
        """A gentle arc: each control point leans sideways by `bend` of the distance.

        The control points stay within the box spanned by `start` and `end`.
        """
        dx, dy = end.x - start.x, end.y - start.y

        def bounded(x: float, y: float) -> ControlPoint:
            return (
                max(min(start.x, end.x), min(max(start.x, end.x), x)),
                max(min(start.y, end.y), min(max(start.y, end.y), y)),
            )

        first, second = bend
        return cls(
            start,
            end,
            duration,
            (
                bounded(
                    start.x + dx * 0.3 - dy * first, start.y + dy * 0.3 + dx * first
                ),
                bounded(
                    start.x + dx * 0.7 - dy * second, start.y + dy * 0.7 + dx * second
                ),
            ),
        )

    @property
    def steps(self) -> int:
        return max(1, math.ceil(self.duration / _FRAME_INTERVAL_SECONDS))

    def point(self, progress: float) -> Point:
        t = _ease(progress)
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
    return CursorPath.curved(start, end, duration if distance >= 2 else 0)


def _ease(progress: float) -> float:
    return 4 * progress**3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2
