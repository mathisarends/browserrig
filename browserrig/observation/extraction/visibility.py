"""Decide whether an element can be seen, and whether something paints over it."""

import re

from .document import Document, Rect, intersect, is_empty
from .styles import Style

_CLIP_RECT = re.compile(r"rect\(([-\d.]+)px,?\s*([-\d.]+)px,?\s*([-\d.]+)px,?\s*([-\d.]+)px\)")
_INSET = re.compile(r"inset\(\s*(\d+(?:\.\d+)?)%")
_TRANSPARENT = frozenset({"", "transparent", "rgba(0, 0, 0, 0)"})
_OPAQUE_TAGS = frozenset({"img", "video", "canvas", "iframe", "embed", "object"})
_MIN_OCCLUDER_AREA = 400
_OVERLAY_POSITIONS = frozenset({"absolute", "fixed", "sticky"})


def hidden(document: Document, index: int, rect: Rect | None) -> bool:
    """True when no amount of scrolling would reveal the element."""
    if rect is None or is_empty(rect) or document.hidden(index):
        return True
    if rect[2] <= 0 or rect[3] <= 0:
        return True
    if document.style(index, Style.VISIBILITY) in ("hidden", "collapse"):
        return True
    clip_path = document.style(index, Style.CLIP_PATH)
    if clip_path not in ("", "none"):
        inset = _INSET.match(clip_path)
        if inset and float(inset[1]) >= 50:
            return True
    clip = _CLIP_RECT.match(document.style(index, Style.CLIP))
    if clip:
        top, right, bottom, left = (float(value) for value in clip.groups())
        if right - left < 2 or bottom - top < 2:
            return True
    clip_area = document.clip(index)
    return clip_area is not None and is_empty(intersect(rect, clip_area))


def visible_area(document: Document, index: int, rect: Rect, viewport: Rect | None) -> Rect | None:
    """The part of `rect` inside the viewport and every scroll container, if any."""
    if viewport is None:
        return None
    area = intersect(
        intersect(intersect(rect, document.clip(index)), document.scroll_clip(index)), viewport
    )
    return None if is_empty(area) else area


class Occlusion:
    """Paint-order index of opaque boxes, to drop controls hidden under overlays."""

    def __init__(self, document: Document, viewport: Rect | None) -> None:
        self._document = document
        self._boxes: list[tuple[int, int, Rect]] = []
        if viewport is None:
            return
        for index in document.elements():
            if not document.is_element(index) or not document.has_layout(index):
                continue
            if not _paints(document, index):
                continue
            rect = document.rect(index)
            if rect is None or hidden(document, index, rect):
                continue
            area = visible_area(document, index, rect, viewport)
            if area is not None and (area[2] - area[0]) * (area[3] - area[1]) >= _MIN_OCCLUDER_AREA:
                self._boxes.append((document.paint_order(index), index, area))
        self._boxes.sort(reverse=True)

    def covered(self, index: int, area: Rect) -> bool:
        """True when one later-painted, unrelated box contains the element's visible area."""
        document = self._document
        paint = document.paint_order(index)
        for order, other, box in self._boxes:
            if order <= paint:
                return False
            if document.contains(other, index) or document.contains(index, other):
                continue
            if (
                box[0] <= area[0] + 1
                and box[1] <= area[1] + 1
                and box[2] >= area[2] - 1
                and box[3] >= area[3] - 1
            ):
                return True
        return False


def _paints(document: Document, index: int) -> bool:
    """Opaque boxes that are positioned or inside a fixed box; static flow does not overlap."""
    if document.style(index, Style.POSITION) not in _OVERLAY_POSITIONS and not document.pinned(
        index
    ):
        return False
    if document.style(index, Style.POINTER_EVENTS) == "none":
        return False
    if document.style(index, Style.VISIBILITY) not in ("", "visible"):
        return False
    if document.tag(index) in _OPAQUE_TAGS:
        return True
    return document.style(index, Style.BACKGROUND_COLOR) not in _TRANSPARENT
