from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import Field

from .options import Options


class Bounds(Options):
    """A rectangle in CSS viewport pixels; clipped rectangles may have no area."""

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)

    def intersect(self, other: Bounds) -> Bounds:
        x, y = max(self.x, other.x), max(self.y, other.y)
        return Bounds(
            x=x,
            y=y,
            width=max(0, min(self.x + self.width, other.x + other.width) - x),
            height=max(0, min(self.y + self.height, other.y + other.height) - y),
        )

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


@dataclass(frozen=True, slots=True)
class FrameTransform:
    """Affine map from one frame's CSS pixels to the top-level viewport.

    The fields are the CSS matrix(a, b, c, d, e, f) of the frame's content box.
    """

    scale_x: float = 1
    skew_y: float = 0
    skew_x: float = 0
    scale_y: float = 1
    offset_x: float = 0
    offset_y: float = 0

    def to_viewport(self, x: float, y: float) -> tuple[float, float]:
        return self.scale_x * x + self.skew_x * y + self.offset_x, (
            self.skew_y * x + self.scale_y * y + self.offset_y
        )

    def to_local(self, x: float, y: float) -> tuple[float, float]:
        determinant = self.scale_x * self.scale_y - self.skew_x * self.skew_y
        if abs(determinant) < 1e-9:
            raise ValueError("Frame transform has no visible area")
        x, y = x - self.offset_x, y - self.offset_y
        return (
            (self.scale_y * x - self.skew_x * y) / determinant,
            (self.scale_x * y - self.skew_y * x) / determinant,
        )

    def bounds_to_viewport(self, bounds: Bounds) -> Bounds:
        return _enclosing(bounds, self.to_viewport)

    def bounds_to_local(self, bounds: Bounds) -> Bounds:
        return _enclosing(bounds, self.to_local)

    def child(self, quad: list[float], width: float, height: float) -> FrameTransform:
        """Compose an embedded frame's transform from its content quad in this space."""
        # Perspective needs a homography. Reject it instead of dispatching a wrong click.
        if any(
            abs(quad[i] + quad[i + 4] - quad[i + 2] - quad[(i + 6) % 8]) > 0.5
            for i in (0, 1)
        ):
            raise ValueError("Perspective-transformed frames are not supported")
        origin = self.to_viewport(quad[0], quad[1])
        right = self.to_viewport(quad[2], quad[3])
        bottom = self.to_viewport(quad[6], quad[7])
        return FrameTransform(
            scale_x=(right[0] - origin[0]) / width,
            skew_y=(right[1] - origin[1]) / width,
            skew_x=(bottom[0] - origin[0]) / height,
            scale_y=(bottom[1] - origin[1]) / height,
            offset_x=origin[0],
            offset_y=origin[1],
        )


class Point(Options):
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class ElementPoint(Point):
    scrolled: bool = False
    bounds: Bounds | None = None


class Geometry(Options):
    x: float = Field(default=0, ge=0)
    y: float = Field(default=0, ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    scale: float = Field(default=1, gt=0)

    def point(self, x: float, y: float) -> tuple[float, float]:
        if not (0 <= x < self.width * self.scale and 0 <= y < self.height * self.scale):
            raise ValueError("Point is outside the observed image")
        return self.x + x / self.scale, self.y + y / self.scale


class Region(Options):
    """A viewport area in CSS pixels, such as a screenshot crop."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)

    def capture(
        self, viewport: Bounds, zoom: float, max_side: float
    ) -> Geometry | None:
        """Clip to `viewport` and cap `zoom` so no image side exceeds `max_side` pixels."""
        visible = Bounds(
            x=self.x, y=self.y, width=self.width, height=self.height
        ).intersect(Bounds(x=0, y=0, width=viewport.width, height=viewport.height))
        if visible.width < 1 or visible.height < 1:
            return None
        scale = max(1.0, min(zoom, max_side / max(visible.width, visible.height)))
        return Geometry(
            x=visible.x,
            y=visible.y,
            width=visible.width,
            height=visible.height,
            scale=scale,
        )


def _enclosing(
    bounds: Bounds, transform: Callable[[float, float], tuple[float, float]]
) -> Bounds:
    points = [
        transform(x, y)
        for x in (bounds.x, bounds.x + bounds.width)
        for y in (bounds.y, bounds.y + bounds.height)
    ]
    xs, ys = zip(*points, strict=True)
    return Bounds(
        x=min(xs), y=min(ys), width=max(xs) - min(xs), height=max(ys) - min(ys)
    )
