from dataclasses import dataclass

from cdpify import CDPCommandError

from browserrig.browser import Frame, Tab
from browserrig.core import Bounds, BrowserError
from browserrig.scripts import FIND, FindArgs, FoundText

# Matches each frame keeps as ranges for marks and listing; more are only counted.
_MARKED_PER_FRAME = 1000


@dataclass(frozen=True, slots=True)
class FindMark:
    """One match in the viewport: its number and its line boxes as (x, y, width, height)."""

    index: int
    rects: tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True, slots=True)
class FoundMatch:
    """A listed match: its number from 1 in page order and its surrounding text."""

    number: int
    found: FoundText


@dataclass(frozen=True, slots=True)
class PageMatches:
    total: int
    # Matches per query, in the order the queries were given.
    counts: tuple[int, ...] = ()
    matches: tuple[FoundMatch, ...] = ()
    # Matches in the viewport, numbered from 1, in viewport CSS pixels.
    marks: tuple[FindMark, ...] = ()
    scrolled: bool = False
    limitations: tuple[str, ...] = ()


async def find_text(
    tab: Tab,
    queries: tuple[str, ...],
    *,
    session: str,
    active: int = 0,
    start: int = 0,
    count: int = 0,
    reveal: bool = False,
) -> PageMatches:
    """Find `queries` in the rendered text of every frame, in page order.

    The queries are alternatives: their matches share one numbering, and where two overlap
    the earlier, then longer, one counts. Matching ignores case, accents and whitespace
    differences but stays within one text block. `active` is the current match, from 0,
    and `reveal` opens collapsed sections around it and scrolls it into view. `start` and
    `count` select the matches returned with their context. Calls sharing `session` reuse
    the page text while it is unchanged.
    """
    if tab.dialog:
        raise BrowserError("Handle the open dialog before searching the page")
    frames = await tab.frames()
    limitations = list(tab.frame_limitations)
    total = 0
    counts = [0] * len(queries)
    matches: list[FoundMatch] = []
    marks: list[FindMark] = []
    scrolled = False
    for frame in frames:
        local_start = max(0, start - total)
        args = FindArgs(
            queries=tuple(queries),
            session=session,
            active=active - total if active >= total else -1,
            start=local_start,
            count=max(0, start + count - total - local_start),
            reveal=reveal,
            clip=frame.local_visible,
        )
        try:
            result = await frame.run(FIND, args)
        except (CDPCommandError, BrowserError, TimeoutError):
            if frame.parent is None:
                raise
            limitations.append(f"Frame {frame.id} changed or could not be searched")
            continue
        if result.total > _MARKED_PER_FRAME:
            limitations.append(
                f"Only the first {_MARKED_PER_FRAME} matches of a document are marked and listed"
            )
        matches += (
            FoundMatch(total + local_start + offset + 1, found)
            for offset, found in enumerate(result.items)
        )
        marks += _viewport_marks(frame, result.marks, first=total + 1)
        scrolled = scrolled or result.scrolled
        total += result.total
        counts = [
            mine + theirs for mine, theirs in zip(counts, result.counts, strict=True)
        ]
    if scrolled:
        # Scrolling moved the frames: mark the matches where they are now.
        tab.layout_changed()
        marks = list(
            (await find_text(tab, queries, session=session, active=active)).marks
        )
    return PageMatches(
        total=total,
        counts=tuple(counts),
        matches=tuple(matches),
        marks=tuple(marks),
        scrolled=scrolled,
        limitations=tuple(dict.fromkeys(limitations)),
    )


async def close_find(tab: Tab) -> None:
    """Drop the page text cached for find in every frame that still has it."""
    try:
        frames = await tab.frames()
    except (CDPCommandError, BrowserError, TimeoutError):
        return
    for frame in frames:
        try:
            await frame.run(FIND, FindArgs(close=True))
        except (CDPCommandError, BrowserError, TimeoutError):
            # A frame that changed or went away took its cache with it.
            continue


def _viewport_marks(frame: Frame, marks, *, first: int) -> list[FindMark]:
    found = []
    for mark in marks:
        rects = []
        for x, y, width, height in mark.rects:
            box = frame.transform.bounds_to_viewport(
                Bounds(x=x, y=y, width=width, height=height)
            )
            if frame.visible is not None:
                box = box.intersect(frame.visible)
            if box.width > 0 and box.height > 0:
                rects.append(
                    (
                        round(box.x, 1),
                        round(box.y, 1),
                        round(box.width, 1),
                        round(box.height, 1),
                    )
                )
        if rects:
            found.append(FindMark(index=first + mark.index, rects=tuple(rects)))
    return found
