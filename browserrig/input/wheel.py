"""Timing for wheel gestures with gentle acceleration and deceleration."""

import math
from dataclasses import dataclass

_FRAME_SECONDS = 1 / 60
_MIN_SECONDS = 0.2
_MAX_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class WheelStep:
    """Native wheel deltas in CSS pixels, with a delay before dispatch.

    The delay runs from the previous dispatch's start, or the gesture's start.
    Slow replies may extend it; steps are never combined to catch up.
    """

    delta_x: float
    delta_y: float
    delay_before_seconds: float = 0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.delta_x, self.delta_y)):
            raise ValueError("Wheel deltas must be finite")
        if (
            not math.isfinite(self.delay_before_seconds)
            or self.delay_before_seconds < 0
        ):
            raise ValueError("Wheel delay must be finite and non-negative")


def scrolling(*, delta_x: float, delta_y: float, speed: float) -> tuple[WheelStep, ...]:
    """Plan a gently eased wheel gesture at a positive speed multiplier."""
    duration_seconds = _duration(math.hypot(delta_x, delta_y)) / speed
    steps = max(1, math.ceil(duration_seconds / _FRAME_SECONDS))
    interval_seconds = duration_seconds / steps
    plan = []
    sent = 0.0
    for frame in range(1, steps + 1):
        progress = _progress(frame / steps)
        plan.append(
            WheelStep(
                delta_x=delta_x * (progress - sent),
                delta_y=delta_y * (progress - sent),
                delay_before_seconds=interval_seconds,
            )
        )
        sent = progress
    return tuple(plan)


def _duration(distance: float) -> float:
    return min(_MAX_SECONDS, max(_MIN_SECONDS, math.sqrt(abs(distance)) / 45))


def _progress(fraction: float) -> float:
    """Ease in and out with zero velocity and acceleration at both ends."""
    if fraction <= 0 or fraction >= 1:
        return 0.0 if fraction <= 0 else 1.0
    return fraction**3 * (10 + fraction * (-15 + 6 * fraction))
