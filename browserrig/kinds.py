"""Closed values shared by event contracts and their producers."""

from enum import StrEnum


class ActivityKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    READINESS = "readiness"
    PAUSED = "paused"


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
    FOCUS = "focus"
    NODE = "node"
    SELECT = "select"
    SET_VALUE = "set_value"


class DragMode(StrEnum):
    POINTER = "pointer"
    HTML5 = "html5"


class ObservationKind(StrEnum):
    WEB = "web"
    FIGMA = "figma"


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
