from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Literal

from harnessed.events import DurableEvent, TransientEvent

from browserrig.kinds import (
    ActionKind,
    ActivityKind,
    ActivityOutcome,
    ObservationKind,
    ReadinessPhase,
    ReadinessStatus,
)


class EventKind(StrEnum):
    """Stable wire tags, independent of Python class names."""

    CONNECTED = "browser.connected"
    DISCONNECTED = "browser.disconnected"
    TAB_OPENED = "browser.tab.opened"
    TAB_ACTIVATED = "browser.tab.activated"
    TAB_CLOSED = "browser.tab.closed"
    NAVIGATION_STARTED = "browser.navigation.started"
    NAVIGATION_COMMITTED = "browser.navigation.committed"
    DIALOG_OPENED = "browser.dialog.opened"
    DIALOG_HANDLED = "browser.dialog.handled"
    DOWNLOAD_COMPLETED = "browser.download.completed"
    DOWNLOAD_STARTED = "browser.download.started"
    DOWNLOAD_FAILED = "browser.download.failed"
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
    RECORDING_STARTED = "browser.recording.started"
    RECORDING_SEGMENT_CLOSED = "browser.recording.segment.closed"
    RECORDING_FINISHED = "browser.recording.finished"
    RECORDING_FAILED = "browser.recording.failed"
    ACTIVITY_STARTED = "browser.activity.started"
    ACTIVITY_FINISHED = "browser.activity.finished"
    CURSOR_MOVED = "browser.cursor.moved"
    CURSOR_STATE = "browser.cursor.state"
    POINTER_PRESSED = "browser.pointer.pressed"
    POINTER_RELEASED = "browser.pointer.released"
    KEY_PRESSED = "browser.key.pressed"
    KEYBOARD_VISIBILITY = "browser.keyboard.visibility"
    SCROLLED = "browser.scrolled"
    ELEMENT_HIGHLIGHTED = "browser.element.highlighted"
    WAITING = "browser.waiting"


@dataclass(frozen=True, slots=True, kw_only=True)
class BrowserEvent(DurableEvent):
    browser_id: str = ""
    target_id: str = ""
    document_id: str = ""
    at: float = field(default_factory=monotonic)


@dataclass(frozen=True, slots=True, kw_only=True)
class InputEvent(TransientEvent):
    browser_id: str = ""
    target_id: str = ""
    document_id: str = ""
    action_id: str = ""
    at: float = field(default_factory=monotonic)


@dataclass(frozen=True, slots=True)
class CursorMovedEvent(InputEvent):
    from_position: tuple[float, float]
    to_position: tuple[float, float]
    control_point_1: tuple[float, float]
    control_point_2: tuple[float, float]
    duration: float
    easing: Literal["easeInOutCubic"] = "easeInOutCubic"
    type: Literal[EventKind.CURSOR_MOVED] = field(default=EventKind.CURSOR_MOVED, kw_only=True)


@dataclass(frozen=True, slots=True)
class CursorStateEvent(InputEvent):
    x: float
    y: float
    buttons: int = 0
    type: Literal[EventKind.CURSOR_STATE] = field(default=EventKind.CURSOR_STATE, kw_only=True)


@dataclass(frozen=True, slots=True)
class PointerPressedEvent(InputEvent):
    x: float
    y: float
    click_count: int
    type: Literal[EventKind.POINTER_PRESSED] = field(
        default=EventKind.POINTER_PRESSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class PointerReleasedEvent(InputEvent):
    x: float
    y: float
    click_count: int
    type: Literal[EventKind.POINTER_RELEASED] = field(
        default=EventKind.POINTER_RELEASED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class KeyPressedEvent(InputEvent):
    key: str
    modifiers: tuple[str, ...] = ()
    duration: float = 0
    type: Literal[EventKind.KEY_PRESSED] = field(default=EventKind.KEY_PRESSED, kw_only=True)


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
class ElementHighlightedEvent(InputEvent):
    ref: str
    x: float
    y: float
    width: float
    height: float
    type: Literal[EventKind.ELEMENT_HIGHLIGHTED] = field(
        default=EventKind.ELEMENT_HIGHLIGHTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class WaitingEvent(InputEvent):
    duration: float
    type: Literal[EventKind.WAITING] = field(default=EventKind.WAITING, kw_only=True)


@dataclass(frozen=True, slots=True)
class ConnectedEvent(BrowserEvent):
    owned_process: bool
    type: Literal[EventKind.CONNECTED] = field(default=EventKind.CONNECTED, kw_only=True)


@dataclass(frozen=True, slots=True)
class DisconnectedEvent(BrowserEvent):
    type: Literal[EventKind.DISCONNECTED] = field(default=EventKind.DISCONNECTED, kw_only=True)


@dataclass(frozen=True, slots=True)
class TabOpenedEvent(BrowserEvent):
    url: str
    opener_id: str = ""
    type: Literal[EventKind.TAB_OPENED] = field(default=EventKind.TAB_OPENED, kw_only=True)


@dataclass(frozen=True, slots=True)
class TabActivatedEvent(BrowserEvent):
    type: Literal[EventKind.TAB_ACTIVATED] = field(default=EventKind.TAB_ACTIVATED, kw_only=True)


@dataclass(frozen=True, slots=True)
class TabClosedEvent(BrowserEvent):
    type: Literal[EventKind.TAB_CLOSED] = field(default=EventKind.TAB_CLOSED, kw_only=True)


@dataclass(frozen=True, slots=True)
class NavigationStartedEvent(BrowserEvent):
    url: str
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
    type: Literal[EventKind.DIALOG_OPENED] = field(default=EventKind.DIALOG_OPENED, kw_only=True)


@dataclass(frozen=True, slots=True)
class DialogHandledEvent(BrowserEvent):
    accepted: bool
    type: Literal[EventKind.DIALOG_HANDLED] = field(default=EventKind.DIALOG_HANDLED, kw_only=True)


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
class ActionStartedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    type: Literal[EventKind.ACTION_STARTED] = field(default=EventKind.ACTION_STARTED, kw_only=True)


@dataclass(frozen=True, slots=True)
class ActionFinishedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    before_url: str
    after_url: str
    before_document: str
    before_fingerprint: str
    before_scroll_y: float
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
    type: Literal[EventKind.ACTION_FAILED] = field(default=EventKind.ACTION_FAILED, kw_only=True)


@dataclass(frozen=True, slots=True)
class ReadinessStartedEvent(BrowserEvent):
    readiness_id: str
    mode: ObservationKind
    phase: ReadinessPhase
    type: Literal[EventKind.READINESS_STARTED] = field(
        default=EventKind.READINESS_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadinessEndedEvent(BrowserEvent):
    readiness_id: str
    mode: ObservationKind
    phase: ReadinessPhase
    duration: float
    reason: str = ""


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
    mode: ObservationKind
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
    type: Literal[EventKind.NUDGE_QUEUED] = field(default=EventKind.NUDGE_QUEUED, kw_only=True)


@dataclass(frozen=True, slots=True)
class NudgeIncludedEvent(BrowserEvent):
    nudge_ids: tuple[str, ...]
    request_id: str
    type: Literal[EventKind.NUDGE_INCLUDED] = field(default=EventKind.NUDGE_INCLUDED, kw_only=True)


@dataclass(frozen=True, slots=True)
class NudgeExpiredEvent(BrowserEvent):
    nudge_id: str
    type: Literal[EventKind.NUDGE_EXPIRED] = field(default=EventKind.NUDGE_EXPIRED, kw_only=True)


@dataclass(frozen=True, slots=True)
class RecordingStartedEvent(BrowserEvent):
    recording_id: str
    type: Literal[EventKind.RECORDING_STARTED] = field(
        default=EventKind.RECORDING_STARTED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class RecordingSegmentClosedEvent(BrowserEvent):
    recording_id: str
    path: str
    sha256: str
    started_at: float
    size: int
    type: Literal[EventKind.RECORDING_SEGMENT_CLOSED] = field(
        default=EventKind.RECORDING_SEGMENT_CLOSED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class RecordingFinishedEvent(BrowserEvent):
    manifest: str
    type: Literal[EventKind.RECORDING_FINISHED] = field(
        default=EventKind.RECORDING_FINISHED, kw_only=True
    )


@dataclass(frozen=True, slots=True)
class RecordingFailedEvent(BrowserEvent):
    reason: str
    type: Literal[EventKind.RECORDING_FAILED] = field(
        default=EventKind.RECORDING_FAILED, kw_only=True
    )


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
    TabClosedEvent,
    NavigationStartedEvent,
    NavigationCommittedEvent,
    DialogOpenedEvent,
    DialogHandledEvent,
    DownloadCompletedEvent,
    DownloadStartedEvent,
    DownloadFailedEvent,
)
ACTION_EVENTS = (ActionStartedEvent, ActionFinishedEvent, ActionFailedEvent)
READINESS_EVENTS = (
    ReadinessStartedEvent,
    ReadyEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessCancelledEvent,
)
NUDGE_EVENTS = (NudgeQueuedEvent, NudgeIncludedEvent, NudgeExpiredEvent)
RECORDING_EVENTS = (
    RecordingStartedEvent,
    RecordingSegmentClosedEvent,
    RecordingFinishedEvent,
    RecordingFailedEvent,
)
ACTIVITY_EVENTS = (ActivityStartedEvent, ActivityFinishedEvent)
INPUT_EVENTS = (
    CursorMovedEvent,
    CursorStateEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    KeyPressedEvent,
    KeyboardVisibilityEvent,
    ScrolledEvent,
    ElementHighlightedEvent,
    WaitingEvent,
)
