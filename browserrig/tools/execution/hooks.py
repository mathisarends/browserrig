from dataclasses import dataclass

from harnessed.kernel import Emit

from browserrig.browser import Tab
from browserrig.core import ActionKind


@dataclass(frozen=True)
class CheckAction(Emit):
    """Validate a managed action before it starts. Raise BrowserError to reject it."""

    tab: Tab
    kind: ActionKind
