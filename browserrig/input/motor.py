import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from browserrig.core import Point

from .pointer import CursorPath, movement

# Seconds between keys a person types, in the page and in the browser's own bars.
TYPING_INTERVAL_SECONDS = 0.05
# The middle of a target, as fractions of its visible box.
CENTER = (0.5, 0.5)


@dataclass(frozen=True, slots=True)
class KeyStroke:
    """One key of typed text: a character, or `Backspace` to erase the last one typed."""

    key: str
    # Seconds before the next key.
    delay_after: float = 0


class Motor(Protocol):
    """How the hand moves: typing rhythm, pointer routes, aim and clicks.

    The devices ask it how to perform input; what viewers see is the `Presenter`'s
    concern. Without one, input runs as fast as the page accepts it.
    """

    def keystrokes(self, text: str, *, sensitive: bool) -> Sequence[KeyStroke]:
        """The keys that type `text`, with the pause after each.

        A plan may slip and correct itself with `Backspace`, or leave a slip in place.
        Sensitive text must be typed exactly as given; only the pauses may vary.
        """
        ...

    def route(self, start: Point, end: Point) -> Sequence[CursorPath]:
        """The pointer's way from `start` to `end`, in strokes that join end to start.

        Their durations pace the native moves; one stroke is a direct move.
        """
        ...

    def aim(self, width: float, height: float) -> tuple[float, float]:
        """Where to point on a target of this size, as fractions of its visible box.

        A spot that something else covers falls back to the target's visible points.
        """
        ...

    def press(self) -> float:
        """Seconds a mouse button stays down for one click."""
        ...

    def landing(self, width: float, height: float) -> Point:
        """Where the pointer first appears in a tab whose viewport has this size."""
        ...


class Instant:
    """Input at machine speed: no pauses, direct pointer moves, centered targets."""

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key) for key in text)

    def route(self, start: Point, end: Point) -> Sequence[CursorPath]:
        return (CursorPath.curved(start, end, 0),)

    def aim(  # pylint: disable=unused-argument
        self, width: float, height: float
    ) -> tuple[float, float]:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, width: float, height: float) -> Point:
        return Point(x=width / 2, y=height / 2)


class HumanMotor:
    """Input at a person's pace: steady typing without slips, eased pointer paths and
    clicks in the middle of a target.

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

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key, self._typing_interval) for key in text)

    def route(self, start: Point, end: Point) -> Sequence[CursorPath]:
        return (movement(start, end),)

    def aim(  # pylint: disable=unused-argument
        self, width: float, height: float
    ) -> tuple[float, float]:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, width: float, height: float) -> Point:
        # Near the middle, but not on the same spot in every tab.
        return Point(
            x=self._rng.uniform(width * 0.4, width * 0.6),
            y=self._rng.uniform(height * 0.4, height * 0.6),
        )
