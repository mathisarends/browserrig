import math
from dataclasses import dataclass
from typing import NamedTuple, Self

from browserrig.core import Point, Position

_FRAME_INTERVAL_SECONDS = 1 / 60


class Bend(NamedTuple):
    """How far each control point leans sideways, as a fraction of the distance."""

    first: float
    second: float


_GENTLE = Bend(0.06, 0.04)


@dataclass(frozen=True, slots=True)
class CursorPath:
    """One eased cubic Bézier stroke of the pointer, taking `duration_seconds` seconds."""

    start: Point
    end: Point
    duration_seconds: float
    control_point_1: Position
    control_point_2: Position

    @classmethod
    def curved(
        cls,
        start: Point,
        end: Point,
        duration_seconds: float,
        *,
        bend: Bend = _GENTLE,
    ) -> Self:
        """A gentle arc: each control point leans sideways by `bend` of the distance.

        The control points stay within the box spanned by `start` and `end`.
        """
        dx, dy = end.x - start.x, end.y - start.y

        def bounded(x: float, y: float) -> Position:
            return Position(
                max(min(start.x, end.x), min(max(start.x, end.x), x)),
                max(min(start.y, end.y), min(max(start.y, end.y), y)),
            )

        return cls(
            start,
            end,
            duration_seconds,
            control_point_1=bounded(
                start.x + dx * 0.3 - dy * bend.first,
                start.y + dy * 0.3 + dx * bend.first,
            ),
            control_point_2=bounded(
                start.x + dx * 0.7 - dy * bend.second,
                start.y + dy * 0.7 + dx * bend.second,
            ),
        )

    @property
    def steps(self) -> int:
        return max(1, math.ceil(self.duration_seconds / _FRAME_INTERVAL_SECONDS))

    def point(self, progress: float) -> Point:
        t = _ease(progress)
        u = 1 - t
        cp1, cp2 = self.control_point_1, self.control_point_2
        return Point(
            x=u**3 * self.start.x
            + 3 * u**2 * t * cp1.x
            + 3 * u * t**2 * cp2.x
            + t**3 * self.end.x,
            y=u**3 * self.start.y
            + 3 * u**2 * t * cp1.y
            + 3 * u * t**2 * cp2.y
            + t**3 * self.end.y,
        )


def movement(start: Point, end: Point) -> CursorPath:
    distance = math.hypot(end.x - start.x, end.y - start.y)
    duration_seconds = min(0.6, max(0.08, 0.05 + 0.075 * math.log2(distance / 20 + 1)))
    return CursorPath.curved(start, end, duration_seconds if distance >= 2 else 0)


def _ease(progress: float) -> float:
    return 4 * progress**3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2
