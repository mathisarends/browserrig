"""Built-in presentation contributions selected by Choreography."""

from collections.abc import Sequence


class Pointer:
    """Cursor movement, buttons, wheel gestures and resting cursor state."""


class Keyboard:
    """Keys and keyboard visibility during page input."""


class TargetHighlight:
    """Highlights on elements located for a tool action."""


class DomScroll:
    """Measured page and element movement from DOM scroll actions."""


class Navigation:
    """Address bar, history and reload gestures."""


class TabSwitch:
    """Tab-strip gestures and cursor re-entry during tab operations."""


class Find:
    """Find bar, simulated keys and live search marks."""


class FileTransfer:
    """File opening and upload animations and upload confirmation."""


class Download:
    """Download progress and completion."""


class Work:
    """Tool and action receipts, including errors and screenshot previews."""


class Activity:
    """Wait scenes and ongoing activity intervals."""


type Contribution = (
    Pointer
    | Keyboard
    | TargetHighlight
    | DomScroll
    | Navigation
    | TabSwitch
    | Find
    | FileTransfer
    | Download
    | Work
    | Activity
)

_DEFAULTS: tuple[type[Contribution], ...] = (
    Pointer,
    Keyboard,
    TargetHighlight,
    DomScroll,
    Navigation,
    TabSwitch,
    Find,
    FileTransfer,
    Download,
    Work,
    Activity,
)


def select(
    only: Sequence[Contribution] | None,
    without: Sequence[type[Contribution]] | None,
) -> frozenset[type[Contribution]]:
    if only is not None and without is not None:
        raise ValueError("Choose either only or without")
    if only is not None:
        selected = frozenset(type(item) for item in only)
        if selected.difference(_DEFAULTS):
            raise TypeError("only expects built-in choreography contribution instances")
        return selected
    excluded = frozenset(without or ())
    if excluded.difference(_DEFAULTS):
        raise TypeError("without expects built-in choreography contribution types")
    return frozenset(_DEFAULTS).difference(excluded)
