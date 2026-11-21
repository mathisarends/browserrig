"""Events of the staged scene: what a viewer sees beyond raw input.

`Choreography` publishes scene events; `ActionLabels` publishes host call events.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from harnessed.models import ToolStatus

from browserrig.core import (
    ActionKind,
    ActivityKind,
    BrowserBar,
    FileTransferDirection,
    Position,
    TabGesture,
    ViewportSize,
)
from browserrig.dom import FindMark
from browserrig.events import (
    EventKind,
    InputEvent,
    LiveEvent,
    PositionedEvent,
    TabEvent,
)
from browserrig.files import FileReadStatus


@dataclass(frozen=True, slots=True)
class PageScrolledEvent(TabEvent):
    """Measured outer-document movement in CSS pixels; emitted only after movement."""

    delta_x: float
    delta_y: float
    type: Literal[EventKind.PAGE_SCROLLED] = field(
        default=EventKind.PAGE_SCROLLED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ElementScrolledEvent(TabEvent):
    """Measured container movement in local CSS pixels; `ref` is observation-local."""

    ref: str
    delta_x: float
    delta_y: float
    type: Literal[EventKind.ELEMENT_SCROLLED] = field(
        default=EventKind.ELEMENT_SCROLLED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class HighlightElementEvent(PositionedEvent):
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
    """Requested wait in seconds, or zero when an active wait is interrupted."""

    duration_seconds: float
    type: Literal[EventKind.WAITING] = field(default=EventKind.WAITING, kw_only=True)


@dataclass(frozen=True, slots=True)
class BarTypedEvent(InputEvent):
    """One key typed into the browser's address or find bar, not into the page.

    `text` is the bar's whole content after the key; `key` is "Enter" when the text is
    submitted. The harness waits `duration_seconds` before the next key.
    """

    browser_bar: BrowserBar
    key: str
    text: str
    duration_seconds: float
    type: Literal[EventKind.BAR_TYPED] = field(
        default=EventKind.BAR_TYPED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FindBarEvent(InputEvent):
    """The find bar opens, as with Ctrl+F, or closes; closing removes every find marker."""

    visible: bool
    type: Literal[EventKind.FIND_BAR] = field(default=EventKind.FIND_BAR, kw_only=True)


@dataclass(frozen=True, slots=True)
class FindResultsEvent(PositionedEvent):
    """Matches for the find bar's text, updated after each key and with the final results.

    `label` is the count the find bar shows. `marks` covers the text matches in the
    viewport, in viewport CSS pixels, and `ticks` where all of them lie as fractions of
    the document height: viewers draw them like a browser's find highlights and
    scrollbar marks. They hold until the next results event or until the find bar
    closes. Nothing is drawn into the page itself.
    """

    query: str
    total: int
    label: str
    marks: tuple[FindMark, ...] = ()
    ticks: tuple[float, ...] = ()
    type: Literal[EventKind.FIND_RESULTS] = field(
        default=EventKind.FIND_RESULTS, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileTransferEvent(PositionedEvent):
    """Files move into a new tab or onto an element for `duration_seconds`."""

    direction: FileTransferDirection
    paths: tuple[str, ...]
    duration_seconds: float
    x: float | None = None
    y: float | None = None
    type: Literal[EventKind.FILE_TRANSFER] = field(
        default=EventKind.FILE_TRANSFER, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabPressedEvent(PositionedEvent):
    """The pointer leaves the page and presses a control in the viewer's tab strip.

    The event belongs to the tab the pointer leaves, starting at `from_position`.
    `tab_id` names the pressed tab; it is empty for the new-tab button. Viewers place
    the control themselves; the harness waits `duration_seconds` before switching tabs.
    """

    gesture: TabGesture
    tab_id: str
    from_position: Position
    duration_seconds: float
    type: Literal[EventKind.TAB_PRESSED] = field(
        default=EventKind.TAB_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class AddressBarFocusedEvent(PositionedEvent):
    """The pointer leaves the page and clicks into the viewer's address bar.

    Like each toolbar press below, the event belongs to the tab the pointer leaves,
    starting at `from_position`, which is None while the pointer has no place there
    yet. Viewers place the control themselves; the harness waits `duration_seconds` before it
    acts, here before the first `BarTypedEvent`. Nothing is clicked in the browser.
    """

    from_position: Position | None
    duration_seconds: float
    type: Literal[EventKind.ADDRESS_BAR_FOCUSED] = field(
        default=EventKind.ADDRESS_BAR_FOCUSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class BackPressedEvent(PositionedEvent):
    """The pointer presses the viewer's back button before the tab goes back."""

    from_position: Position | None
    duration_seconds: float
    type: Literal[EventKind.BACK_PRESSED] = field(
        default=EventKind.BACK_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ForwardPressedEvent(PositionedEvent):
    """The pointer presses the viewer's forward button before the tab goes forward."""

    from_position: Position | None
    duration_seconds: float
    type: Literal[EventKind.FORWARD_PRESSED] = field(
        default=EventKind.FORWARD_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ReloadPressedEvent(PositionedEvent):
    """The pointer presses the viewer's reload button before the tab reloads."""

    from_position: Position | None
    duration_seconds: float
    type: Literal[EventKind.RELOAD_PRESSED] = field(
        default=EventKind.RELOAD_PRESSED, kw_only=True
    )


type ToolbarPressedEvent = (
    AddressBarFocusedEvent | BackPressedEvent | ForwardPressedEvent | ReloadPressedEvent
)


@dataclass(frozen=True, slots=True)
class CursorEnteredEvent(PositionedEvent):
    """After a tab or toolbar press, the pointer returns into this tab's page.

    It travels to `to_position`, where this tab last had the pointer; the harness waits
    `duration_seconds` before dispatching native input there. After a toolbar press it follows
    once the control has acted; if that failed or was cancelled, `duration_seconds` is zero.
    """

    to_position: Position
    duration_seconds: float
    easing: Literal["easeInOutCubic"] = "easeInOutCubic"
    type: Literal[EventKind.CURSOR_ENTERED] = field(
        default=EventKind.CURSOR_ENTERED, kw_only=True
    )


class WorkPhase(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CaptureRegion:
    """An immutable rectangle in the source tab's viewport CSS pixels.

    The receipt's `viewport` gives the size of that viewport at capture time.
    """

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PresentedEvent(LiveEvent):
    """Status that `Choreography` projected from browser facts for people watching.

    Viewers draw these instead of the facts. Terminal receipts expire after their
    `retention` seconds.
    """


@dataclass(frozen=True, slots=True)
class WorkPresentedEvent(PresentedEvent):
    """Bounded, redacted work receipt for inert overlays and external viewers.

    Preview text is data, never HTML. A screenshot receipt is completed only after
    the requested observation has actually captured an image. A nonempty `label`
    carries redacted model-written text for host UIs; `title` keeps its fixed caption.
    """

    work_id: str
    kind: ActionKind | None
    title: str
    phase: WorkPhase
    call_id: str = ""
    tool_name: str = ""
    label: str = ""
    action_id: str = ""
    detail: str = ""
    source_url: str = ""
    source_path: str = ""
    characters: int | None = None
    offset: int = 0
    next_offset: int | None = None
    page_number: int | None = None
    page_count: int | None = None
    content_status: FileReadStatus | None = None
    preview: str = ""
    limitations: tuple[str, ...] = ()
    artifact_path: str = ""
    image_url: str = field(default="", repr=False)
    region: CaptureRegion | None = None
    # The source viewport `region` lies in, measured with the capture.
    viewport: ViewportSize | None = None
    elapsed: float = 0
    retention: float = 8
    type: Literal[EventKind.WORK_PRESENTED] = field(
        default=EventKind.WORK_PRESENTED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", WorkPhase(self.phase))
        if self.kind is not None:
            object.__setattr__(self, "kind", ActionKind(self.kind))


@dataclass(frozen=True, slots=True)
class DownloadPresentedEvent(PresentedEvent):
    """One download as viewers show it; upsert by `download_id`.

    Every receipt names the file. `total_bytes` is None while the size is unknown.
    """

    download_id: str
    filename: str
    phase: WorkPhase
    received_bytes: int = 0
    total_bytes: int | None = None
    reason: str = ""
    retention: float = 2.2
    type: Literal[EventKind.DOWNLOAD_PRESENTED] = field(
        default=EventKind.DOWNLOAD_PRESENTED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", WorkPhase(self.phase))


@dataclass(frozen=True, slots=True)
class UploadPresentedEvent(PresentedEvent):
    """Files placed into a page's file input; `ref` is observation-local."""

    paths: tuple[str, ...]
    ref: str = ""
    retention: float = 8
    type: Literal[EventKind.UPLOAD_PRESENTED] = field(
        default=EventKind.UPLOAD_PRESENTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ActivityPresentedEvent(PresentedEvent):
    """An activity interval, such as model thinking or a handoff, begins or ends."""

    interval_id: str
    kind: ActivityKind
    active: bool
    type: Literal[EventKind.ACTIVITY_PRESENTED] = field(
        default=EventKind.ACTIVITY_PRESENTED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind(self.kind))


class ToolCallPhase(StrEnum):
    REQUESTED = "requested"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class ActionEnvelope:
    """A display snapshot, redacted before publication, with no live session state."""

    action_label: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallPresentedEvent(LiveEvent):
    """A complete call's redacted display envelope for host UIs, separate from replay data.

    The built-in overlay does not consume this event. Missing or invalid model labels
    produce an empty `envelope.action_label`; finished calls also carry their status.
    """

    call_id: str
    tool_name: str
    phase: ToolCallPhase
    envelope: ActionEnvelope = field(default_factory=ActionEnvelope)
    status: ToolStatus | None = None
    type: Literal[EventKind.TOOL_CALL_PRESENTED] = field(
        default=EventKind.TOOL_CALL_PRESENTED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", ToolCallPhase(self.phase))
        if self.status is not None:
            object.__setattr__(self, "status", ToolStatus(self.status))


SCENE_EVENTS = (
    PageScrolledEvent,
    ElementScrolledEvent,
    HighlightElementEvent,
    WaitingEvent,
    BarTypedEvent,
    FindBarEvent,
    FindResultsEvent,
    FileTransferEvent,
    TabPressedEvent,
    AddressBarFocusedEvent,
    BackPressedEvent,
    ForwardPressedEvent,
    ReloadPressedEvent,
    CursorEnteredEvent,
    WorkPresentedEvent,
    DownloadPresentedEvent,
    UploadPresentedEvent,
    ActivityPresentedEvent,
)
