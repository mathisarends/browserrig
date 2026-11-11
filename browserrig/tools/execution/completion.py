from collections.abc import Awaitable, Callable
from time import monotonic

from harnessed.tracing import span, traced

from browserrig.browser import Browser, Tab
from browserrig.core import (
    ActionContext,
    ActionKind,
    BrowserError,
    ReadinessPhase,
    ReadinessStatus,
)
from browserrig.readiness import Readiness
from browserrig.tools.effects import Effect

from .policy import FOLLOWED_KINDS, NAVIGATION_KINDS

# Input that requests a new tab gives the browser time to open it.
_TAB_OPEN_SECONDS = 3.0


class Completion:
    """Dispatch input and wait for the page or tab it leads into."""

    def __init__(
        self, browser: Browser, readiness: Readiness, actions: ActionContext
    ) -> None:
        self._browser = browser
        self._readiness = readiness
        self._actions = actions

    async def dispatch(
        self,
        tab: Tab,
        kind: ActionKind,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
        *,
        settle: bool,
    ) -> tuple[Effect, str, str]:
        """Run input in `tab`, then wait for its page, or for a tab the input opened.

        Returns the effect, a readiness note and a note on the tab that opened.
        """
        started = monotonic()
        mark = self._browser.tabs.openings
        with self._actions.activate(action_id), span("browserrig.operation"):
            effect = await operation(tab)
        settled = settle and not tab.closed
        note = (
            await self._settle(tab, kind, started)
            if settled and not effect.opens_tab
            else ""
        )
        if kind not in FOLLOWED_KINDS or tab.closed:
            return effect, note, ""
        with self._actions.activate(action_id):
            followed = await self._follow(tab, mark, expected=effect.opens_tab)
        if effect.opens_tab and not followed:
            # Nothing opened, so the input acted in this tab instead.
            if settled:
                note = await self._settle(tab, kind, started)
            followed = " No new tab opened; the input acted in this tab."
        return effect, note, followed

    @traced
    async def navigate(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
    ) -> tuple[Effect, str]:
        effects: list[Effect] = []

        async def dispatch() -> None:
            with self._actions.activate(action_id), span("browserrig.operation"):
                effects.append(await operation(tab))

        report = await self._readiness.wait(
            tab, phase=ReadinessPhase.NAVIGATION, dispatch=dispatch
        )
        effect = (
            effects[0]
            if effects
            else Effect("Navigation requested; completion is not confirmed.")
        )
        note = (
            ""
            if report.status == ReadinessStatus.READY
            else f" Readiness is {report.status}: {report.reason}."
        )
        return effect, note

    @traced
    async def _settle(self, tab: Tab, kind: ActionKind, started: float) -> str:
        phase = (
            ReadinessPhase.NAVIGATION
            if kind in NAVIGATION_KINDS
            else ReadinessPhase.AFTER_ACTION
        )
        try:
            report = await self._readiness.wait(tab, phase=phase, since=started)
        except BrowserError as error:
            return (
                f" Action executed; follow-up observation is unavailable: {error}. "
                "Do not repeat blindly."
            )
        if report.status != ReadinessStatus.READY:
            return f" Action executed; readiness is {report.status}: {report.reason}."
        return ""

    @traced
    async def _follow(self, tab: Tab, mark: int, *, expected: bool) -> str:
        """Activate a tab the input opened and wait for its page, as Chrome shows it.

        Input that asked for a new tab gives the browser a moment to open it; other input
        has already settled, so a tab it opened is attached by now.
        """
        opened = await self._browser.tabs.opened_since(
            mark, timeout=_TAB_OPEN_SECONDS if expected else 0
        )
        if opened is None:
            return ""
        await self._browser.tabs.activate(opened.id)
        report = await self._readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
        note = (
            f" It opened tab {opened.id}, which is now active; "
            f"the previous tab is {tab.id}."
        )
        if report.status != ReadinessStatus.READY:
            note += f" Readiness is {report.status}: {report.reason}."
        return note
