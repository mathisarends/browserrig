from enum import StrEnum


class ActivityKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    READINESS = "readiness"
    COMPACTION = "compaction"
    PAUSED = "paused"


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
    WRITE_FILE = "write_file"
    OPEN_FILE = "open_file"
    OPEN_DOWNLOADED_FILE = "open_downloaded_file"
    OBSERVE = "observe"
    SCREENSHOT = "screenshot"
    EXTRACT_CONTENT = "extract_content"
    # Kept readable in existing persisted action receipts.
    TAB = "tab"


class ElementOperation(StrEnum):
    POINT = "point"
    BOUNDS = "bounds"
    FOCUS = "focus"
    SELECT = "select"
    SET_VALUE = "set_value"


class DragMode(StrEnum):
    POINTER = "pointer"
    HTML5 = "html5"


class MouseEventKind(StrEnum):
    MOVED = "mouseMoved"
    PRESSED = "mousePressed"
    RELEASED = "mouseReleased"
    WHEEL = "mouseWheel"


class ObservationKind(StrEnum):
    DOM = "dom"
    CANVAS = "canvas"


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
