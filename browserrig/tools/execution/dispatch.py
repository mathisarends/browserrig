from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import NamedTuple

from harnessed.tracing import span, traced

from browserrig.browser import Browser, Tab
from browserrig.core import (
    ActionContext,
    BrowserError,
    ReadinessPhase,
    ReadinessStatus,
)
from browserrig.readiness import PageReadiness
from browserrig.tools.effects import Effect

from .policy import ActionProfile

# Input that requests a new tab gives the browser time to open it.
_TAB_OPEN_SECONDS = 3.0


class ActionDispatch:
    """Dispatch input and wait for the page or tab it leads into."""

    def __init__(
        self, browser: Browser, readiness: PageReadiness, actions: ActionContext
    ) -> None:
        self._browser = browser
        self._readiness = readiness
        self._actions = actions

    async def dispatch(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
        *,
        profile: ActionProfile,
        settle: bool,
    ) -> Dispatched:
        """Run input in `tab`, then wait for its page, or for a tab the input opened."""
        started = monotonic()
        mark = self._browser.tabs.openings
        with self._actions.activate(action_id), span("browserrig.operation"):
            effect = await operation(tab)
        phase = profile.phase or ReadinessPhase.AFTER_ACTION
        settled = settle and not tab.closed
        note = (
            await self._settle(tab, phase, started)
            if settled and not effect.expects_new_tab
            else ""
        )
        if not profile.follow_opened_tab or tab.closed:
            return Dispatched(effect, note, "")
        timeout_seconds = _TAB_OPEN_SECONDS if effect.expects_new_tab else 0
        with self._actions.activate(action_id):
            followed = await self._follow(tab, mark, timeout_seconds=timeout_seconds)
        if effect.expects_new_tab and not followed:
            # Nothing opened, so the input acted in this tab instead.
            if settled:
                note = await self._settle(tab, phase, started)
            followed = " No new tab opened; the input acted in this tab."
        return Dispatched(effect, note, followed)

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
                effect = await operation(tab)
                effects.append(effect)

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
    async def _settle(self, tab: Tab, phase: ReadinessPhase, started: float) -> str:
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
    async def _follow(self, tab: Tab, mark: int, *, timeout_seconds: float) -> str:
        """Activate a tab the input opened and wait for its page."""
        opened = await self._browser.tabs.opened_since(
            mark, timeout_seconds=timeout_seconds
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


class Dispatched(NamedTuple):
    """The effect of dispatched input with its readiness note and opened-tab note."""

    effect: Effect
    note: str
    followed: str
