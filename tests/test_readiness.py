# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Context, Inject, Plugin
from harnessed.testing import ScriptedModel

from browserrig import Readiness, ReadinessOptions, wait_for_page
from browserrig.events import ReadinessDegradedEvent, ReadinessStartedEvent, ReadyEvent
from tests.fakes import FakeBrowser, FakeChrome


class Access(Plugin, needs=(Readiness,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, _ctx: Context, readiness: Inject[Readiness]):
        self.holder["readiness"] = readiness


async def test_readiness_deduplicates_waiters_and_one_cancellation_does_not_cancel_other():
    holder = {}
    options = ReadinessOptions(quiet_ms=0, navigation_min_ms=40, poll_interval=0.005)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        readiness, tab = holder["readiness"], holder["browser"].active_tab
        first = asyncio.create_task(readiness.wait(tab, phase="initial"))
        second = asyncio.create_task(readiness.wait(tab, phase="initial"))
        await asyncio.sleep(0.005)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        report = await second
        assert report.status == "ready"
        assert (
            len([e for e in session.events if isinstance(e, ReadinessStartedEvent)])
            == 1
        )


async def test_endless_dom_mutation_is_explicitly_degraded():
    holder = {}
    options = ReadinessOptions(timeout=0.03, poll_interval=0.005, navigation_min_ms=0)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        holder["browser"].active_tab.quiet_ms = 0
        report = await holder["readiness"].wait(holder["browser"].active_tab)
        assert report.status == "degraded"
        assert "changing" in report.reason
        assert any(isinstance(e, ReadinessDegradedEvent) for e in session.events)


async def test_plugin_state_is_per_session():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[Access(holder), Readiness(), FakeChrome(holder)],
    )
    async with agent.session():
        first = holder["readiness"]
        first_events = first._events
        assert first_events is holder["browser"].events
        first._state.initialized.add(("sentinel", "doc"))
    async with agent.session():
        second = holder["readiness"]
        assert second is not first
        assert second._events is holder["browser"].events
        assert second._events is not first_events
        assert not second._state.initialized
    with pytest.raises(RuntimeError):
        _ = first._events


async def test_readiness_events_keep_start_document_when_navigation_finishes(
    monkeypatch,
):
    events = []
    browser = FakeBrowser(SimpleNamespace(emit=AsyncMock(side_effect=events.append)))
    tab = browser.active_tab

    async def check(_strategy):
        tab.document_id = "new-document"
        return True

    monkeypatch.setattr("browserrig.readiness.wait._check", check)
    report = await wait_for_page(tab, events=browser.events)
    start = next(event for event in events if isinstance(event, ReadinessStartedEvent))
    end = next(event for event in events if isinstance(event, ReadyEvent))
    assert start.readiness_id == end.readiness_id
    assert start.document_id == end.document_id == "doc-1"
    assert report.document_id == "new-document"
