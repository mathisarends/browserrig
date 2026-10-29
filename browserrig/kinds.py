from enum import StrEnum


class ActivityKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    READINESS = "readiness"
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
    NAVIGATE = "navigate"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    DRAG = "drag"
    TYPE = "type"
    PRESS = "press"
    SCROLL = "scroll"
    SELECT = "select"
    UPLOAD = "upload"
    TAB = "tab"


class ElementOperation(StrEnum):
    POINT = "point"
    BOUNDS = "bounds"
    FOCUS = "focus"
    NODE = "node"
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
