"""Timing for smooth wheel scrolling, modeled on Chrome's own smooth scroll.

Measured in Chrome, `scrollBy({behavior: 'smooth'})` closely follows
cubic-bezier(0.4, 0, 0, 1) and lasts about one 60 Hz frame per square root of the
distance in pixels.
"""

import math

FRAME_SECONDS = 1 / 60
_MIN_SECONDS = 0.15
_MAX_SECONDS = 1.5


def wheel_duration(distance: float) -> float:
    return min(
        _MAX_SECONDS, max(_MIN_SECONDS, math.sqrt(abs(distance)) * FRAME_SECONDS)
    )


def wheel_progress(fraction: float) -> float:
    """Chrome's smooth scroll curve: a soft start, a fast middle and a long gentle settle."""
    if fraction <= 0 or fraction >= 1:
        return 0.0 if fraction <= 0 else 1.0
    return _cubic_bezier(0.4, 0.0, 0.0, 1.0, fraction)


def _cubic_bezier(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    def sample(a: float, b: float, t: float) -> float:
        return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t**2 * b + t**3

    # x(t) increases monotonically for CSS curves, so bisection always finds t.
    low, high = 0.0, 1.0
    for _ in range(30):
        middle = (low + high) / 2
        if sample(x1, x2, middle) < x:
            low = middle
        else:
            high = middle
    return sample(y1, y2, (low + high) / 2)
