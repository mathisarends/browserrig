import random
from typing import Protocol

from browserrig.core import Point

from .pointer import CursorPath, movement

# Seconds between keys a person types, in the page and in the browser's own bars.
TYPING_INTERVAL_SECONDS = 0.05


class Motor(Protocol):
    """How the hand moves: typing rhythm, pointer paths and where the pointer lands.

    The devices ask it how to perform input; what viewers see is the `Presenter`'s
    concern. Without one, input runs as fast as the page accepts it.
    """

    def typing_interval(self) -> float:
        """Seconds between keys typed into the page."""
        ...

    def path(self, start: Point, end: Point) -> CursorPath:
        """The pointer's way from `start` to `end`; its duration paces the native moves."""
        ...

    def landing(self, width: float, height: float) -> Point:
        """Where the pointer first appears in a tab whose viewport has this size."""
        ...


class Instant:
    """Input at machine speed: no pauses, straight pointer moves, centered landing."""

    def typing_interval(self) -> float:
        return 0

    def path(self, start: Point, end: Point) -> CursorPath:
        return CursorPath(start, end, 0)

    def landing(self, width: float, height: float) -> Point:
        return Point(x=width / 2, y=height / 2)


class HumanMotor:
    """Input at a person's pace: steady typing and eased pointer paths.

    `rng` draws the varying parts, such as where the pointer lands in a new tab; pass a
    seeded `random.Random` for repeatable runs.
    """

    def __init__(
        self,
        *,
        typing_interval: float = TYPING_INTERVAL_SECONDS,
        rng: random.Random | None = None,
    ) -> None:
        if typing_interval < 0:
            raise ValueError("typing_interval must not be negative")
        self._typing_interval = typing_interval
        self._rng = rng or random.Random()

    def typing_interval(self) -> float:
        return self._typing_interval

    def path(self, start: Point, end: Point) -> CursorPath:
        return movement(start, end)

    def landing(self, width: float, height: float) -> Point:
        # Near the middle, but not on the same spot in every tab.
        return Point(
            x=self._rng.uniform(width * 0.4, width * 0.6),
            y=self._rng.uniform(height * 0.4, height * 0.6),
        )
