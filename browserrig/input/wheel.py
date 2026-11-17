"""Timing for wheel gestures with gentle acceleration and deceleration."""

import math

FRAME_SECONDS = 1 / 60
_MIN_SECONDS = 0.2
_MAX_SECONDS = 1.5


def wheel_duration(distance: float) -> float:
    return min(_MAX_SECONDS, max(_MIN_SECONDS, math.sqrt(abs(distance)) / 45))


def wheel_progress(fraction: float) -> float:
    """Ease in and out with zero velocity and acceleration at both ends."""
    if fraction <= 0 or fraction >= 1:
        return 0.0 if fraction <= 0 else 1.0
    return fraction**3 * (10 + fraction * (-15 + 6 * fraction))
