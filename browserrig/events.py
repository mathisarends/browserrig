from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Literal

from harnessed.events import DurableEvent, TransientEvent

from .core import (
    ActionKind,
    ActivityKind,
    ActivityOutcome,
    CursorStyle,
    FileSource,
    HandoffStatus,
    ReadinessPhase,
    ReadinessStage,
    ReadinessStatus,
)


class EventKind(StrEnum):
    """Stable wire tags, independent of Python class names."""

    CONNECTED = "browser.connected"
    DISCONNECTED = "browser.disconnected"
    TAB_OPENED = "browser.tab.opened"
    TAB_ACTIVATED = "browser.tab.activated"
    TAB_CLOSING = "browser.tab.closing"
    TAB_CLOSED = "browser.tab.closed"
    TAB_UPDATED = "browser.tab.updated"
    NAVIGATION_STARTED = "browser.navigation.started"
    NAVIGATION_COMMITTED = "browser.navigation.committed"
    DIALOG_OPENED = "browser.dialog.opened"
    DIALOG_HANDLED = "browser.dialog.handled"
    DOWNLOAD_COMPLETED = "browser.download.completed"
    DOWNLOAD_STARTED = "browser.download.started"
    DOWNLOAD_FAILED = "browser.download.failed"
    DOWNLOAD_CANCELED = "browser.download.canceled"
    DOWNLOAD_PROGRESS = "browser.download.progress"
    FILES_LISTED = "browser.files.listed"
    FILE_READ_STARTED = "browser.files.read.started"
    FILE_READ_FINISHED = "browser.files.read.finished"
    FILE_READ_FAILED = "browser.files.read.failed"
    FILE_WRITTEN = "browser.files.written"
    FILE_OPENED = "browser.files.opened"
    FILES_UPLOADED = "browser.files.uploaded"
    FILE_TRANSFER = "browser.files.transfer"
    ACTION_STARTED = "browser.action.started"
    ACTION_FINISHED = "browser.action.finished"
    ACTION_FAILED = "browser.action.failed"
    READINESS_STARTED = "browser.readiness.started"
    READINESS_READY = "browser.readiness.ready"
    READINESS_DEGRADED = "browser.readiness.degraded"
    READINESS_FAILED = "browser.readiness.failed"
    READINESS_CANCELLED = "browser.readiness.cancelled"
    OBSERVATION_CAPTURED = "browser.observation.captured"
    NUDGE_QUEUED = "browser.nudge.queued"
    NUDGE_INCLUDED = "browser.nudge.included"
    NUDGE_EXPIRED = "browser.nudge.expired"
    SECRET_ENTERED = "browser.secret.entered"
    ACTIVITY_STARTED = "browser.activity.started"
    ACTIVITY_FINISHED = "browser.activity.finished"
    HANDOFF_REQUESTED = "browser.handoff.requested"
    HANDOFF_FINISHED = "browser.handoff.finished"
    CURSOR_MOVED = "browser.cursor.moved"
    CURSOR_STATE = "browser.cursor.state"
    CURSOR_STYLE = "browser.cursor.style"
    CURSOR_ENTERED = "browser.cursor.entered"
    TAB_PRESSED = "browser.tab.pressed"
    POINTER_PRESSED = "browser.pointer.pressed"
    POINTER_RELEASED = "browser.pointer.released"
    KEY_PRESSED = "browser.key.pressed"
    KEYBOARD_VISIBILITY = "browser.keyboard.visibility"
    SCROLLED = "browser.scrolled"
    HIGHLIGHT_ELEMENT = "browser.element.highlight"
    WAITING = "browser.waiting"
    BAR_TYPED = "browser.bar.typed"
    FIND_BAR = "browser.find.bar"
    FIND_RESULTS = "browser.find.results"


@dataclass(frozen=True, slots=True, kw_only=True)
class BrowserEvent(DurableEvent):
    browser_id: str = ""
    target_id: str = ""
    document_id: str = ""
    at: float = field(default_factory=monotonic)


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveEvent(TransientEvent):
    """Live presentation detail that is streamed to subscribers but never persisted."""

    browser_id: str = ""
    target_id: str = ""
    document_id: str = ""
    at: float = field(default_factory=monotonic)


@dataclass(frozen=True, slots=True, kw_only=True)
class InputEvent(LiveEvent):
    action_id: str = ""


@dataclass(frozen=True, slots=True)
class CursorMovedEvent(InputEvent):
    from_position: tuple[float, float]
    to_position: tuple[float, float]
    control_point_1: tuple[float, float]
    control_point_2: tuple[float, float]
    duration: float
    easing: Literal["easeInOutCubic"] = "easeInOutCubic"
    type: Literal[EventKind.CURSOR_MOVED] = field(
        default=EventKind.CURSOR_MOVED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class CursorStateEvent(InputEvent):
    x: float
    y: float
    buttons: int = 0
    type: Literal[EventKind.CURSOR_STATE] = field(
        default=EventKind.CURSOR_STATE, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class CursorStyleEvent(InputEvent):
    """The CSS cursor under the pointer changed, for example to a hand over a link."""

    style: CursorStyle
    type: Literal[EventKind.CURSOR_STYLE] = field(
        default=EventKind.CURSOR_STYLE, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class PointerPressedEvent(InputEvent):
    x: float
    y: float
    click_count: int
    button: str = "left"
    type: Literal[EventKind.POINTER_PRESSED] = field(
        default=EventKind.POINTER_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class PointerReleasedEvent(InputEvent):
    x: float
    y: float
    click_count: int
    button: str = "left"
    type: Literal[EventKind.POINTER_RELEASED] = field(
        default=EventKind.POINTER_RELEASED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class KeyPressedEvent(InputEvent):
    key: str
    modifiers: tuple[str, ...] = ()
    duration: float = 0
    type: Literal[EventKind.KEY_PRESSED] = field(
        default=EventKind.KEY_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class KeyboardVisibilityEvent(InputEvent):
    visible: bool
    type: Literal[EventKind.KEYBOARD_VISIBILITY] = field(
        default=EventKind.KEYBOARD_VISIBILITY, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ScrolledEvent(InputEvent):
    x: float
    y: float
    delta_x: float
    delta_y: float
    duration: float
    type: Literal[EventKind.SCROLLED] = field(default=EventKind.SCROLLED, kw_only=True)


@dataclass(frozen=True, slots=True)
class DownloadProgressedEvent(LiveEvent):
    """Byte progress reported by the browser; completion is only a separate durable event."""

    download_id: str
    received_bytes: int
    total_bytes: int | None = None
    type: Literal[EventKind.DOWNLOAD_PROGRESS] = field(
        default=EventKind.DOWNLOAD_PROGRESS, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabUpdatedEvent(LiveEvent):
    """What a viewer's tab strip shows for one tab, sent whenever any field changes.

    `favicon` is a `data:` URI loaded through the browser, or empty when the page has
    none. A loading tab keeps its previous icon until the new page settles.
    """

    url: str
    title: str
    loading: bool
    favicon: str = ""
    type: Literal[EventKind.TAB_UPDATED] = field(
        default=EventKind.TAB_UPDATED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ConnectedEvent(BrowserEvent):
    owned_process: bool
    type: Literal[EventKind.CONNECTED] = field(
        default=EventKind.CONNECTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DisconnectedEvent(BrowserEvent):
    type: Literal[EventKind.DISCONNECTED] = field(
        default=EventKind.DISCONNECTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabOpenedEvent(BrowserEvent):
    url: str
    opener_id: str = ""
    type: Literal[EventKind.TAB_OPENED] = field(
        default=EventKind.TAB_OPENED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabActivatedEvent(BrowserEvent):
    type: Literal[EventKind.TAB_ACTIVATED] = field(
        default=EventKind.TAB_ACTIVATED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabClosingEvent(BrowserEvent):
    """A controlled tab is about to close; consumers can flush its resources."""

    type: Literal[EventKind.TAB_CLOSING] = field(
        default=EventKind.TAB_CLOSING, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class TabClosedEvent(BrowserEvent):
    type: Literal[EventKind.TAB_CLOSED] = field(
        default=EventKind.TAB_CLOSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class NavigationStartedEvent(BrowserEvent):
    """`typed` is what a person would enter in the address bar to get to `url`.

    It drops the scheme of web URLs; for a search it is the query itself.
    """

    url: str
    typed: str = ""
    type: Literal[EventKind.NAVIGATION_STARTED] = field(
        default=EventKind.NAVIGATION_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class NavigationCommittedEvent(BrowserEvent):
    url: str
    type: Literal[EventKind.NAVIGATION_COMMITTED] = field(
        default=EventKind.NAVIGATION_COMMITTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DialogOpenedEvent(BrowserEvent):
    kind: str
    message: str
    type: Literal[EventKind.DIALOG_OPENED] = field(
        default=EventKind.DIALOG_OPENED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DialogHandledEvent(BrowserEvent):
    accepted: bool
    type: Literal[EventKind.DIALOG_HANDLED] = field(
        default=EventKind.DIALOG_HANDLED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DownloadCompletedEvent(BrowserEvent):
    download_id: str
    filename: str
    size: int
    type: Literal[EventKind.DOWNLOAD_COMPLETED] = field(
        default=EventKind.DOWNLOAD_COMPLETED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DownloadStartedEvent(BrowserEvent):
    download_id: str
    filename: str
    url: str
    type: Literal[EventKind.DOWNLOAD_STARTED] = field(
        default=EventKind.DOWNLOAD_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DownloadFailedEvent(BrowserEvent):
    download_id: str
    reason: str
    type: Literal[EventKind.DOWNLOAD_FAILED] = field(
        default=EventKind.DOWNLOAD_FAILED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class DownloadCanceledEvent(BrowserEvent):
    download_id: str
    type: Literal[EventKind.DOWNLOAD_CANCELED] = field(
        default=EventKind.DOWNLOAD_CANCELED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FilesListedEvent(BrowserEvent):
    directory: str
    entries: int
    offset: int = 0
    next_offset: int | None = None
    type: Literal[EventKind.FILES_LISTED] = field(
        default=EventKind.FILES_LISTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileReadStartedEvent(BrowserEvent):
    """A read was requested; extraction and OCR may take seconds before it finishes."""

    read_id: str
    path: str
    page_number: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    member: str | None = None
    ocr: bool | None = None
    offset: int = 0
    type: Literal[EventKind.FILE_READ_STARTED] = field(
        default=EventKind.FILE_READ_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileReadFinishedEvent(BrowserEvent):
    read_id: str
    path: str
    format: str
    status: str
    characters: int
    offset: int = 0
    next_offset: int | None = None
    page_number: int | None = None
    page_count: int | None = None
    sheet: str | None = None
    member: str | None = None
    type: Literal[EventKind.FILE_READ_FINISHED] = field(
        default=EventKind.FILE_READ_FINISHED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileReadFailedEvent(BrowserEvent):
    read_id: str
    path: str
    reason: str
    type: Literal[EventKind.FILE_READ_FAILED] = field(
        default=EventKind.FILE_READ_FAILED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileWrittenEvent(BrowserEvent):
    path: str
    size: int
    created: bool
    type: Literal[EventKind.FILE_WRITTEN] = field(
        default=EventKind.FILE_WRITTEN, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FileOpenedEvent(BrowserEvent):
    """A file was opened in the tab identified by `target_id`."""

    path: str
    source: FileSource
    download_id: str = ""
    type: Literal[EventKind.FILE_OPENED] = field(
        default=EventKind.FILE_OPENED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class FilesUploadedEvent(BrowserEvent):
    paths: tuple[str, ...]
    ref: str
    type: Literal[EventKind.FILES_UPLOADED] = field(
        default=EventKind.FILES_UPLOADED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ActionStartedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    type: Literal[EventKind.ACTION_STARTED] = field(
        default=EventKind.ACTION_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PageState:
    url: str
    document_id: str
    fingerprint: str = ""
    scroll_y: float = 0


@dataclass(frozen=True, slots=True)
class ActionFinishedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    before: PageState
    after_url: str
    prepared_scroll: bool = False
    expects_change: bool = False
    type: Literal[EventKind.ACTION_FINISHED] = field(
        default=EventKind.ACTION_FINISHED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ActionFailedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    dispatched: bool
    reason: str
    type: Literal[EventKind.ACTION_FAILED] = field(
        default=EventKind.ACTION_FAILED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ReadinessStartedEvent(BrowserEvent):
    readiness_id: str
    phase: ReadinessPhase
    stage: ReadinessStage = field(default=ReadinessStage.ONGOING, kw_only=True)
    type: Literal[EventKind.READINESS_STARTED] = field(
        default=EventKind.READINESS_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadinessEndedEvent(BrowserEvent):
    readiness_id: str
    phase: ReadinessPhase
    stage: ReadinessStage = field(default=ReadinessStage.ONGOING, kw_only=True)
    duration: float
    reason: str = ""
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ReadyEvent(ReadinessEndedEvent):
    type: Literal[EventKind.READINESS_READY] = field(
        default=EventKind.READINESS_READY, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ReadinessDegradedEvent(ReadinessEndedEvent):
    type: Literal[EventKind.READINESS_DEGRADED] = field(
        default=EventKind.READINESS_DEGRADED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ReadinessFailedEvent(ReadinessEndedEvent):
    type: Literal[EventKind.READINESS_FAILED] = field(
        default=EventKind.READINESS_FAILED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ReadinessCancelledEvent(ReadinessEndedEvent):
    type: Literal[EventKind.READINESS_CANCELLED] = field(
        default=EventKind.READINESS_CANCELLED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class ObservationCapturedEvent(BrowserEvent):
    observation_id: str
    url: str
    fingerprint: str
    scroll_y: float
    readiness: ReadinessStatus
    type: Literal[EventKind.OBSERVATION_CAPTURED] = field(
        default=EventKind.OBSERVATION_CAPTURED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class NudgeQueuedEvent(BrowserEvent):
    nudge_id: str
    key: str
    text: str
    cause_id: str
    type: Literal[EventKind.NUDGE_QUEUED] = field(
        default=EventKind.NUDGE_QUEUED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class NudgeIncludedEvent(BrowserEvent):
    nudge_ids: tuple[str, ...]
    request_id: str
    type: Literal[EventKind.NUDGE_INCLUDED] = field(
        default=EventKind.NUDGE_INCLUDED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class NudgeExpiredEvent(BrowserEvent):
    nudge_id: str
    type: Literal[EventKind.NUDGE_EXPIRED] = field(
        default=EventKind.NUDGE_EXPIRED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class SecretEnteredEvent(BrowserEvent):
    """Names the secrets typed and where; values are never part of an event."""

    names: tuple[str, ...]
    origin: str
    type: Literal[EventKind.SECRET_ENTERED] = field(
        default=EventKind.SECRET_ENTERED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class HandoffRequestedEvent(BrowserEvent):
    handoff_id: str
    reason: str
    expected_state: str = ""
    source: Literal["tool", "pause"] = "tool"
    call_id: str = ""
    type: Literal[EventKind.HANDOFF_REQUESTED] = field(
        default=EventKind.HANDOFF_REQUESTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class HandoffFinishedEvent(BrowserEvent):
    handoff_id: str
    status: HandoffStatus
    note: str = ""
    changes: tuple[str, ...] = ()
    source: Literal["tool", "pause"] = "tool"
    call_id: str = ""
    type: Literal[EventKind.HANDOFF_FINISHED] = field(
        default=EventKind.HANDOFF_FINISHED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HandoffStatus(self.status))


@dataclass(frozen=True, slots=True)
class ActivityStartedEvent(BrowserEvent):
    interval_id: str
    kind: ActivityKind
    cause_id: str
    epoch_id: str = ""
    type: Literal[EventKind.ACTIVITY_STARTED] = field(
        default=EventKind.ACTIVITY_STARTED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind(self.kind))


@dataclass(frozen=True, slots=True)
class ActivityFinishedEvent(BrowserEvent):
    interval_id: str
    kind: ActivityKind
    cause_id: str
    started_at: float
    outcome: ActivityOutcome
    epoch_id: str = ""
    reason: str = ""
    type: Literal[EventKind.ACTIVITY_FINISHED] = field(
        default=EventKind.ACTIVITY_FINISHED, kw_only=True
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind(self.kind))
        object.__setattr__(self, "outcome", ActivityOutcome(self.outcome))


BROWSER_EVENTS = (
    ConnectedEvent,
    DisconnectedEvent,
    TabOpenedEvent,
    TabActivatedEvent,
    TabClosingEvent,
    TabClosedEvent,
    NavigationStartedEvent,
    NavigationCommittedEvent,
    DialogOpenedEvent,
    DialogHandledEvent,
    DownloadCompletedEvent,
    DownloadStartedEvent,
    DownloadFailedEvent,
    DownloadCanceledEvent,
    DownloadProgressedEvent,
)
FILE_EVENTS = (
    FilesListedEvent,
    FileReadStartedEvent,
    FileReadFinishedEvent,
    FileReadFailedEvent,
    FileWrittenEvent,
    FileOpenedEvent,
)
UPLOAD_EVENTS = (FilesUploadedEvent,)
ACTION_EVENTS = (ActionStartedEvent, ActionFinishedEvent, ActionFailedEvent)
READINESS_EVENTS = (
    ReadinessStartedEvent,
    ReadyEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessCancelledEvent,
)
NUDGE_EVENTS = (NudgeQueuedEvent, NudgeIncludedEvent, NudgeExpiredEvent)
SECRET_EVENTS = (SecretEnteredEvent,)
HANDOFF_EVENTS = (HandoffRequestedEvent, HandoffFinishedEvent)
ACTIVITY_EVENTS = (ActivityStartedEvent, ActivityFinishedEvent)
TAB_STRIP_EVENTS = (TabUpdatedEvent,)
INPUT_EVENTS = (
    CursorMovedEvent,
    CursorStateEvent,
    CursorStyleEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    KeyPressedEvent,
    KeyboardVisibilityEvent,
    ScrolledEvent,
)
