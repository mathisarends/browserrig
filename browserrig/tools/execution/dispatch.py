from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import NamedTuple

from harnessed.tracing import traced

from browserrig.browser import Tab, Tabs
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
        self, tabs: Tabs, readiness: PageReadiness, actions: ActionContext
    ) -> None:
        self._tabs = tabs
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
        mark = self._tabs.openings
        with self._actions.activate(action_id):
            effect = await operation(tab)
        phase = profile.phase or ReadinessPhase.AFTER_ACTION
        settled = settle and not tab.closed
        if not profile.follow_opened_tab or tab.closed:
            note = (
                await self._settle(tab, phase, started)
                if settled and not effect.expects_new_tab
                else ""
            )
            return Dispatched(effect, note, "")

        note = ""
        if effect.expects_new_tab:
            opened = await self._tabs.opened_since(
                mark, timeout_seconds=_TAB_OPEN_SECONDS
            )
        elif settled:
            opened, note = await self._settle_or_open(tab, phase, started, mark)
        else:
            opened = await self._tabs.opened_since(mark)

        if opened is not None:
            with self._actions.activate(action_id):
                followed = await self._follow(tab, opened)
            return Dispatched(effect, note, followed)

        if not effect.expects_new_tab:
            return Dispatched(effect, note, "")
        note = await self._settle(tab, phase, started) if settled else ""
        return Dispatched(
            effect, note, " No new tab opened; the input acted in this tab."
        )

    @traced
    async def navigate(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
    ) -> tuple[Effect, str]:
        effects: list[Effect] = []

        async def dispatch() -> None:
            with self._actions.activate(action_id):
                effect = await operation(tab)
                effects.append(effect)

        report = await self._readiness.wait(
            tab, phase=ReadinessPhase.NAVIGATION, dispatch=dispatch
        )
        effect = (
            effects[0]
            if effects
            else Effect(
                "Navigation requested; completion is not confirmed.",
                blocked_reason=report.reason or "Navigation did not dispatch",
            )
        )
        note = (
            ""
            if report.status == ReadinessStatus.READY
            else f" Readiness is {report.status}: {report.reason}."
        )
        return effect, note

    async def _settle_or_open(
        self, tab: Tab, phase: ReadinessPhase, started: float, mark: int
    ) -> tuple[Tab | None, str]:
        opened = await self._tabs.opened_since(mark)
        if opened is not None:
            return opened, ""

        settle = asyncio.create_task(self._settle(tab, phase, started))
        opening = asyncio.create_task(
            self._tabs.opened_since(mark, timeout_seconds=_TAB_OPEN_SECONDS)
        )
        try:
            done, _ = await asyncio.wait(
                (settle, opening), return_when=asyncio.FIRST_COMPLETED
            )
            if opening in done and (opened := opening.result()) is not None:
                return opened, ""
            note = await settle
            return await self._tabs.opened_since(mark), note
        finally:
            settle.cancel()
            opening.cancel()
            await asyncio.gather(settle, opening, return_exceptions=True)

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
    async def _follow(self, tab: Tab, opened: Tab) -> str:
        """Activate a tab the input opened and wait for its page."""
        await self._tabs.follow_opened(opened)
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
