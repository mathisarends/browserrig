from abc import ABC, abstractmethod

from browserrig.browser import Tab
from browserrig.core.kinds import ReadinessStatus

from .config import ReadinessOptions


class ReadinessStrategy(ABC):
    """How a readiness policy decides that a document is ready.

    `wait_for_page` owns the shared loop: deadline, dialogs, document changes and events.
    A strategy only probes the page and reports what it saw.
    """

    budget: float

    def __init__(self, tab: Tab, options: ReadinessOptions) -> None:
        self._tab = tab
        self._options = options
        self.delay = options.poll_interval
        self.reason = ""

    @abstractmethod
    async def check(self) -> bool:
        """Probe once; True when ready. Set `reason` and `delay` for the next poll."""

    @abstractmethod
    def timeout_status(self) -> ReadinessStatus:
        """The outcome when the budget runs out before `check` succeeded."""
