"""Lifecycle defaults selected from a browser tool's stable action kind."""

from dataclasses import dataclass, replace

from browserrig.core import ActionKind, ReadinessPhase


@dataclass(frozen=True, slots=True)
class ActionProfile:
    """The preparation and follow-up performed around one browser action."""

    phase: ReadinessPhase | None = ReadinessPhase.AFTER_ACTION
    requires_observation: bool = False
    preflight: bool = False
    expects_change: bool = False
    follow_opened_tab: bool = False
    check_chain: bool = False


def action_profile(kind: ActionKind) -> ActionProfile | None:
    """Return the lifecycle for an action, or None for a passive tool."""
    return _PROFILES.get(kind)


_PAGE = ActionProfile()
_TAB = ActionProfile(phase=None)
_NAVIGATION = ActionProfile(phase=ReadinessPhase.NAVIGATION)
_POINTER = ActionProfile(requires_observation=True, follow_opened_tab=True)
_POINTER_MUTATION = replace(_POINTER, expects_change=True)
_CLICK = replace(_POINTER_MUTATION, check_chain=True)
_KEY = replace(_POINTER, check_chain=True)
_FORM = replace(_KEY, preflight=True)

_PROFILES = {
    ActionKind.CLICK: _CLICK,
    ActionKind.CLICK_AT: _POINTER_MUTATION,
    ActionKind.MOVE_MOUSE: _POINTER,
    ActionKind.DOUBLE_CLICK: _CLICK,
    ActionKind.DRAG: _POINTER_MUTATION,
    ActionKind.DRAG_AT: _POINTER_MUTATION,
    ActionKind.TYPE: _FORM,
    ActionKind.PRESS: _KEY,
    ActionKind.SELECT: _FORM,
    ActionKind.SELECT_OPTIONS: _FORM,
    ActionKind.SET_DATE: _FORM,
    ActionKind.TAB: _TAB,
    ActionKind.OPEN_TAB: _TAB,
    ActionKind.SWITCH_TAB: _TAB,
    ActionKind.CLOSE_TAB: _TAB,
    ActionKind.OPEN_FILE: _TAB,
    ActionKind.OPEN_DOWNLOADED_FILE: _TAB,
    ActionKind.NAVIGATE: _NAVIGATION,
    ActionKind.SEARCH: _NAVIGATION,
    ActionKind.GO_BACK: _NAVIGATION,
    ActionKind.GO_FORWARD: _NAVIGATION,
    ActionKind.RELOAD: _NAVIGATION,
    ActionKind.SCROLL: _PAGE,
    ActionKind.SCROLL_PAGE: _PAGE,
    ActionKind.SCROLL_ELEMENT: _PAGE,
    ActionKind.JAVASCRIPT: _PAGE,
    ActionKind.UPLOAD: ActionProfile(preflight=True),
}
