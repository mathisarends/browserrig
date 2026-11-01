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

    def pointer_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        """Plan consecutive cursor strokes from `start` to `destination`.

        Stroke endpoints must meet; their durations pace native mouse movement.
        """
        ...

    def aim_fractions(
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        """Choose horizontal and vertical fractions within the target's visible box.

        A spot that something else covers falls back to the target's visible points.
        """
        ...

    def press(self) -> float:
        """Seconds a mouse button stays down for one click."""
        ...

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        """Initial cursor position in viewport pixels; built-in motors use the center."""
        ...


class Instant:
    """Input at machine speed: no pauses, direct pointer moves, centered targets."""

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key) for key in text)

    def pointer_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return (CursorPath.curved(start, destination, 0),)

    def aim_fractions(  # pylint: disable=unused-argument
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        return Point(x=viewport_width / 2, y=viewport_height / 2)


class HumanMotor:
    """Input at a person's pace: steady typing without slips, eased pointer paths and
    clicks in the middle of a target.
    """

    def __init__(
        self,
        *,
        typing_interval: float = TYPING_INTERVAL_SECONDS,
    ) -> None:
        if typing_interval < 0:
            raise ValueError("typing_interval must not be negative")
        self._typing_interval = typing_interval

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key, self._typing_interval) for key in text)

    def pointer_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return (movement(start, destination),)

    def aim_fractions(  # pylint: disable=unused-argument
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        return Point(x=viewport_width / 2, y=viewport_height / 2)
