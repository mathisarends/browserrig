"""Events of the staged scene: what a viewer sees beyond raw input.

They are only emitted while the `Choreography` plugin is mounted.
"""

from dataclasses import dataclass, field
from typing import Literal

from browserrig.core import BrowserBar, FileTransferDirection, TabGesture
from browserrig.events import EventKind, InputEvent
from browserrig.observation import FindMark


@dataclass(frozen=True, slots=True)
class HighlightElementEvent(InputEvent):
    ref: str
    x: float
    y: float
    width: float
    height: float
    type: Literal[EventKind.HIGHLIGHT_ELEMENT] = field(
        default=EventKind.HIGHLIGHT_ELEMENT, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class WaitingEvent(InputEvent):
    duration: float
    type: Literal[EventKind.WAITING] = field(default=EventKind.WAITING, kw_only=True)


@dataclass(frozen=True, slots=True)
class BarTypedEvent(InputEvent):
    """One key typed into the browser's address or find bar, not into the page.

    `text` is the bar's whole content after the key; `key` is "Enter" when the text is
    submitted. The harness waits `duration` before the next key.
    """

    browser_bar: BrowserBar
    key: str
    text: str
    duration: float
    type: Literal[EventKind.BAR_TYPED] = field(
        default=EventKind.BAR_TYPED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FindBarEvent(InputEvent):
    """The find bar opens, as with Ctrl+F, or closes; closing removes every find marker."""

    visible: bool
    type: Literal[EventKind.FIND_BAR] = field(default=EventKind.FIND_BAR, kw_only=True)


@dataclass(frozen=True, slots=True)
class FindResultsEvent(InputEvent):
    """Matches for the find bar's text, updated after each key and after scrolling to one.

    `active` numbers the current match from 1, or is 0 without one, of `total`. `marks`
    covers the matches in the viewport, in viewport CSS pixels: viewers draw them like a
    browser's find highlights, the active one distinct. They hold until the next results
    event or until the find bar closes; the page shows the same markers meanwhile.
    """

    query: str
    total: int
    active: int
    marks: tuple[FindMark, ...] = ()
    type: Literal[EventKind.FIND_RESULTS] = field(
        default=EventKind.FIND_RESULTS, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileTransferEvent(InputEvent):
    """Files move into a new tab or onto a page element; the harness waits for `duration`."""

    direction: FileTransferDirection
    paths: tuple[str, ...]
    duration: float
    x: float | None = None
    y: float | None = None
    type: Literal[EventKind.FILE_TRANSFER] = field(
        default=EventKind.FILE_TRANSFER, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabPressedEvent(InputEvent):
    """The pointer leaves the page and presses a control in the viewer's tab strip.

    The event belongs to the tab the pointer leaves, starting at `from_position`.
    `tab_id` names the pressed tab; it is empty for the new-tab button. Viewers place
    the control themselves; the harness waits `duration` before switching tabs.
    """

    gesture: TabGesture
    tab_id: str
    from_position: tuple[float, float]
    duration: float
    type: Literal[EventKind.TAB_PRESSED] = field(
        default=EventKind.TAB_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class CursorEnteredEvent(InputEvent):
    """After a tab press, the pointer returns from the tab strip into this tab's page.

    It travels to `to_position`, where this tab last had the pointer; the harness waits
    `duration` before dispatching native input there.
    """

    to_position: tuple[float, float]
    duration: float
    easing: Literal["easeInOutCubic"] = "easeInOutCubic"
    type: Literal[EventKind.CURSOR_ENTERED] = field(
        default=EventKind.CURSOR_ENTERED, kw_only=True
    )


SCENE_EVENTS = (
    HighlightElementEvent,
    WaitingEvent,
    BarTypedEvent,
    FindBarEvent,
    FindResultsEvent,
    FileTransferEvent,
    TabPressedEvent,
    CursorEnteredEvent,
)
