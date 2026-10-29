import asyncio

import pytest
import yaml
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, tool
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Browser, LaunchBrowser, browser_plugins
from browserrig.events import ActivityFinishedEvent

pytestmark = pytest.mark.integration


async def test_pause_steer_resume_observes_external_page_change(site):
    started, release = asyncio.Event(), asyncio.Event()
    holder = {}

    class Gate(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            holder["browser"] = browser

        @tool
        async def hold(self) -> str:
            started.set()
            await release.wait()
            return "Step finished"

    model = ScriptedModel([call(Gate.hold), "Resumed"])
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(LaunchBrowser(url=site)),
            Gate(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        handle = await session.submit("Inspect the page")
        async with asyncio.timeout(10):
            await started.wait()
            pause = asyncio.create_task(session.pause())
            await asyncio.sleep(0)
            release.set()
            await pause
            assert len(model.requests) == 1
            await session.steer("Look for the changed title")
            await holder["browser"].active_tab.evaluate("document.title='Changed during pause'")
            await session.resume()
            result = await handle.result()
        assert result.text == "Resumed"
        latest = next(
            yaml.safe_load(msg.text)
            for msg in reversed(model.requests[-1].messages)
            if msg.text.startswith("page:\n")
        )
        assert latest["page"]["title"] == "Changed during pause"
        assert any("Look for the changed title" in msg.text for msg in model.requests[-1].messages)
        assert any(
            isinstance(e, ActivityFinishedEvent) and e.kind == "paused" for e in session.events
        )
