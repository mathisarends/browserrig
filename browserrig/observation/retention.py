from dataclasses import dataclass
from typing import Protocol


class ImageRetention(Protocol):
    """Decides how many of the oldest images to drop once a new one was added."""

    def overflow(self, count: int) -> int:
        """Return how many oldest images to discard from `count` retained images."""


@dataclass(frozen=True, slots=True, init=False)
class TrimInBatches:
    """Keep at most ``max_images``; on overflow drop the oldest until ``min_images`` remain.

    Each trim changes the prompt prefix once instead of on every step. ``min_images``
    defaults to half of ``max_images`` (at least one).
    """

    max_images: int
    min_images: int

    def __init__(self, max_images: int = 1, min_images: int | None = None) -> None:
        min_images = _retention_minimum(max_images, min_images)
        object.__setattr__(self, "max_images", max_images)
        object.__setattr__(self, "min_images", min_images)

    def overflow(self, count: int) -> int:
        return count - self.min_images if count > self.max_images else 0


@dataclass(frozen=True, slots=True)
class UntilCompaction:
    """Never trim; images leave history together with the steps compaction summarizes."""

    def overflow(self, count: int) -> int:  # pylint: disable=unused-argument
        return 0


def _retention_minimum(max_images: int, min_images: int | None) -> int:
    """Normalize and validate one retention window before freezing its bounds."""
    if min_images is None:
        min_images = max(1, max_images // 2) if _positive(max_images) else max_images
    if not _positive(max_images) or not _positive(min_images):
        raise ValueError("max_images and min_images must be positive integers")
    if min_images > max_images:
        raise ValueError("min_images must not exceed max_images")
    return min_images


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1
