import asyncio

import pytest
from harnessed import Agent, Context, Inject, Plugin
from harnessed.testing import ScriptedModel

from browserrig import Readiness, ReadinessOptions
from browserrig.events import ReadinessDegradedEvent, ReadinessStartedEvent
from tests.fakes import FakeChrome


class Access(Plugin, needs=(Readiness,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, ctx: Context, readiness: Inject[Readiness]):
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
        assert len([e for e in session.events if isinstance(e, ReadinessStartedEvent)]) == 1


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
        model=ScriptedModel(["ok"]), plugins=[FakeChrome(holder), Readiness(), Access(holder)]
    )
    async with agent.session("first"):
        first = holder["readiness"]
        first.state.geometry[("sentinel", "doc")] = object()
    async with agent.session("second"):
        second = holder["readiness"]
        assert second is not first
        assert not second.state.geometry
