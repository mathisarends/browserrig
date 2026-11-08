import asyncio
from unittest.mock import AsyncMock

import pytest
from harnessed import Plugin, PolicyDecision, tool
from harnessed.kernel import PluginScope, needs
from harnessed.models import UserMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import (
    Agent,
    Browser,
    Chrome,
    HandoffStatus,
    HumanHandoff,
    HumanResponse,
)
from browserrig.events import ActivityFinishedEvent, HandoffFinishedEvent
from tests.javascript import evaluate
from tests.observations import latest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("handoff_enabled", [False, True])
async def test_pause_steer_resume_observes_external_page_change(site, handoff_enabled):
    started, release = asyncio.Event(), asyncio.Event()
    holder = {}

    class Gate(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _ctx: PluginScope):
            browser = self._setup_browser
            holder["browser"] = browser

        @tool
        async def hold(self) -> str:
            started.set()
            await release.wait()
            return "Step finished"

    model = ScriptedModel([call(Gate.hold), "Resumed"])
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[
            Approvals(default=PolicyDecision.ALLOW),
            HumanHandoff(ask=AsyncMock(return_value=HumanResponse()))
            if handoff_enabled
            else None,
            Gate(),
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
            await session.append_message(UserMessage("Do not submit forms."))
            assert len(model.requests) == 1
            if not handoff_enabled:
                await session.inbox.steer("Look for the changed title")
            await evaluate(
                holder["browser"].active_tab, "document.title='Changed during pause'"
            )
            await session.resume()
            result = await handle.result()
        assert result.text == "Resumed"
        assert any(
            msg.text == "Do not submit forms." for msg in model.requests[-1].messages
        )
        state = latest(model.requests[-1].messages)
        assert state["page"]["title"] == "Changed during pause"
        if handoff_enabled:
            history = session.scope[HumanHandoff].history
            assert history[-1].status is HandoffStatus.RESUMED
            assert any(
                "Changed during pause" in change for change in history[-1].changes
            )
        else:
            assert any(
                "Look for the changed title" in msg.text
                for msg in model.requests[-1].messages
            )
        assert any(
            isinstance(e, ActivityFinishedEvent) and e.kind == "paused"
            for e in result.events
        )


async def test_handoff_observes_human_navigation_and_a_short_lived_popup(site):
    holder = {}

    class BrowserHandle(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _ctx: PluginScope):
            browser = self._setup_browser
            holder["browser"] = browser

    async def ask(_request):
        browser = holder["browser"]
        tab = browser.active_tab
        popup = await browser.tabs.open(f"{site}/other")
        await browser.tabs.close(popup.id)
        await browser.tabs.activate(tab.id)
        await tab.navigate(f"{site}/other")
        return HumanResponse()

    model = ScriptedModel(
        [
            call("request_human", reason="Log in", expected_state="Other page visible"),
            "Continued",
        ]
    )
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[HumanHandoff(ask=ask), BrowserHandle()],
    )
    async with agent.session() as session:
        result = await session.run("Continue after login")
        history = session.scope[HumanHandoff].history
    assert result.text == "Continued"
    assert latest(model.requests[-1].messages)["page"]["title"] == "Other"
    receipt = history[-1]
    assert receipt.status is HandoffStatus.DONE and receipt.human_note == ""
    assert any("tab.opened" in change for change in receipt.changes)
    assert any("tab.closed" in change for change in receipt.changes)
    assert any(isinstance(event, HandoffFinishedEvent) for event in result.events)
