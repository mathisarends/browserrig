"""Lifecycle defaults selected from a browser tool's stable action kind."""

from browserrig.core import ActionKind

# Pointer actions aim at coordinates from the last observation, so it must still be current.
POINTER_KINDS = frozenset(
    {
        ActionKind.CLICK,
        ActionKind.CLICK_AT,
        ActionKind.MOVE_MOUSE,
        ActionKind.DOUBLE_CLICK,
        ActionKind.DRAG,
        ActionKind.DRAG_AT,
    }
)
CHAINABLE_KINDS = {
    ActionKind.CLICK,
    ActionKind.DOUBLE_CLICK,
    ActionKind.TYPE,
    ActionKind.PRESS,
    ActionKind.SELECT,
    ActionKind.SELECT_OPTIONS,
    ActionKind.SET_DATE,
}
TAB_KINDS = {
    ActionKind.TAB,
    ActionKind.OPEN_TAB,
    ActionKind.SWITCH_TAB,
    ActionKind.CLOSE_TAB,
    ActionKind.OPEN_FILE,
    ActionKind.OPEN_DOWNLOADED_FILE,
}
NAVIGATION_KINDS = {
    ActionKind.NAVIGATE,
    ActionKind.SEARCH,
    ActionKind.GO_BACK,
    ActionKind.GO_FORWARD,
    ActionKind.RELOAD,
}
ACTION_KINDS = (
    POINTER_KINDS
    | CHAINABLE_KINDS
    | TAB_KINDS
    | NAVIGATION_KINDS
    | {
        ActionKind.SCROLL,
        ActionKind.SCROLL_PAGE,
        ActionKind.SCROLL_ELEMENT,
        ActionKind.JAVASCRIPT,
        ActionKind.UPLOAD,
    }
)
PREFLIGHT_KINDS = {
    ActionKind.TYPE,
    ActionKind.SELECT,
    ActionKind.SELECT_OPTIONS,
    ActionKind.SET_DATE,
    ActionKind.UPLOAD,
}
EXPECTED_CHANGES = {
    ActionKind.CLICK,
    ActionKind.CLICK_AT,
    ActionKind.DOUBLE_CLICK,
    ActionKind.DRAG,
    ActionKind.DRAG_AT,
}
# Page input that opens a tab, like a target=_blank link, leads into it as in Chrome.
FOLLOWED_KINDS = POINTER_KINDS | CHAINABLE_KINDS
