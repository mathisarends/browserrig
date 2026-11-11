from enum import StrEnum
from typing import Self


class ActivityKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    READINESS = "readiness"
    COMPACTION = "compaction"
    PAUSED = "paused"
    HANDOFF = "handoff"


class ActivityOutcome(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    CLOSED = "closed"
    INTERRUPTED = "interrupted"
    ABORTED = "aborted"
    CONTEXT_LIMIT = "context_limit"
    STOPPED = "stopped"
    MAX_STEPS = "max_steps"
    TOKEN_BUDGET = "token_budget"
    REJECTED = "rejected"
    DISCARDED = "discarded"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class HandoffStatus(StrEnum):
    """Human handoff outcomes with stable serialized values."""

    DONE = "done"
    DECLINED = "declined"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RESUMED = "resumed"


class ActionKind(StrEnum):
    """Stable tool identities, independent of Python callback names and signatures."""

    NAVIGATE = "navigate"
    SEARCH = "search"
    GO_BACK = "go_back"
    GO_FORWARD = "go_forward"
    RELOAD = "reload"
    WAIT = "wait"
    JAVASCRIPT = "javascript"
    CLICK = "click"
    CLICK_AT = "click_at"
    MOVE_MOUSE = "move_mouse"
    DOUBLE_CLICK = "double_click"
    DRAG = "drag"
    DRAG_AT = "drag_at"
    TYPE = "type"
    PRESS = "press"
    SCROLL = "scroll"
    SCROLL_PAGE = "scroll_page"
    SCROLL_ELEMENT = "scroll_element"
    SELECT = "select"
    SET_DATE = "set_date"
    UPLOAD = "upload"
    OPEN_TAB = "open_tab"
    SWITCH_TAB = "switch_tab"
    CLOSE_TAB = "close_tab"
    LIST_TABS = "list_tabs"
    HANDLE_DIALOG = "handle_dialog"
    LIST_DOWNLOADS = "list_downloads"
    LIST_FILES = "list_files"
    READ_FILE = "read_file"
    GLOB = "glob"
    GREP = "grep"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    OPEN_FILE = "open_file"
    OPEN_DOWNLOADED_FILE = "open_downloaded_file"
    SCREENSHOT = "screenshot"
    EXTRACT_CONTENT = "extract_content"
    FIND_IN_PAGE = "find_in_page"
    # Kept readable in existing persisted action receipts.
    TAB = "tab"


class ElementOperation(StrEnum):
    POINT = "point"
    BOUNDS = "bounds"
    FOCUS = "focus"
    FOCUSED = "focused"
    SELECT = "select"
    SET_VALUE = "set_value"
    TEXT_STATE = "text_state"


class MouseEventKind(StrEnum):
    MOVED = "mouseMoved"
    PRESSED = "mousePressed"
    RELEASED = "mouseReleased"
    WHEEL = "mouseWheel"


class CursorStyle(StrEnum):
    """CSS cursor keywords that a live viewer can draw for the agent's pointer."""

    DEFAULT = "default"
    POINTER = "pointer"
    TEXT = "text"
    VERTICAL_TEXT = "vertical-text"
    CROSSHAIR = "crosshair"
    CELL = "cell"
    MOVE = "move"
    GRAB = "grab"
    GRABBING = "grabbing"
    ALL_SCROLL = "all-scroll"
    NOT_ALLOWED = "not-allowed"
    NO_DROP = "no-drop"
    COPY = "copy"
    ALIAS = "alias"
    CONTEXT_MENU = "context-menu"
    HELP = "help"
    PROGRESS = "progress"
    WAIT = "wait"
    ZOOM_IN = "zoom-in"
    ZOOM_OUT = "zoom-out"
    COL_RESIZE = "col-resize"
    ROW_RESIZE = "row-resize"
    N_RESIZE = "n-resize"
    E_RESIZE = "e-resize"
    S_RESIZE = "s-resize"
    W_RESIZE = "w-resize"
    NE_RESIZE = "ne-resize"
    NW_RESIZE = "nw-resize"
    SE_RESIZE = "se-resize"
    SW_RESIZE = "sw-resize"
    EW_RESIZE = "ew-resize"
    NS_RESIZE = "ns-resize"
    NESW_RESIZE = "nesw-resize"
    NWSE_RESIZE = "nwse-resize"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> Self:
        """Unknown, custom-image and fallback-only values show the default arrow."""
        keyword = value.rsplit(",", 1)[-1].strip().lower()
        try:
            return cls(keyword)
        except ValueError:
            return cls(cls.DEFAULT)


class FileTransferDirection(StrEnum):
    OPEN = "open"
    UPLOAD = "upload"


class BrowserBar(StrEnum):
    """Text fields of the browser itself, outside the page."""

    ADDRESS = "address"
    FIND = "find"


class TabGesture(StrEnum):
    """Which tab-strip control the pointer presses: a tab, the new-tab button or a tab's close."""

    ACTIVATE = "activate"
    OPEN = "open"
    CLOSE = "close"


class FileSource(StrEnum):
    WORKSPACE = "workspace"
    DOWNLOAD = "download"


class ReadinessStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReadinessPhase(StrEnum):
    INITIAL = "initial"
    OBSERVATION = "observation"
    NAVIGATION = "navigation"
    ACTION = "action"
    AFTER_ACTION = "after_action"


class ReadinessStage(StrEnum):
    INITIAL = "initial"
    ONGOING = "ongoing"
