from unittest.mock import AsyncMock

import pytest
from harnessed import Context, Inject, Plugin, PolicyDecision
from harnessed.events import ToolCallFinishedEvent
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Browser, BrowserAgent, LaunchBrowser
from browserrig.events import ActionStartedEvent, ActivityStartedEvent
from browserrig.kinds import ActivityKind

pytestmark = pytest.mark.integration


async def test_facade_reopens_native_sessions_and_owns_a_fresh_browser_per_session(site, tmp_path):
    browsers = []

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            browsers.append(browser)

    model = ScriptedModel(["First answer", "Restored answer"])
    agent = BrowserAgent(
        model=model,
        browser=LaunchBrowser(url=site),
        session_directory=tmp_path / "sessions",
        plugins=[Access()],
    )
    async with agent.session("conversation") as session:
        first = await session.run("Remember this page")
        assert first.text == "First answer"
    assert not browsers[0].client.is_connected
    assert (tmp_path / "sessions" / "conversation.jsonl").is_file()
    async with agent.session("conversation") as session:
        second = await session.run("Continue the conversation")
        assert second.text == "Restored answer"
        assert any("First answer" in msg.text for msg in model.requests[-1].messages)
        epochs = {
            item.epoch_id
            for item in session.events
            if isinstance(item, ActivityStartedEvent) and item.kind is ActivityKind.LLM
        }
        assert len(epochs) == 2
    assert len(browsers) == 2
    assert browsers[0].id != browsers[1].id
    assert not browsers[1].client.is_connected


async def test_facade_honors_explicit_tool_policy(site):
    model = ScriptedModel([call("navigate", url=site + "/other"), "Denied"])
    agent = BrowserAgent(
        model=model,
        browser=LaunchBrowser(url=site),
        approvals=Approvals(default=PolicyDecision.ALLOW, deny=["navigate"]),
    )
    result = await agent.run("Try navigation")
    assert result.text == "Denied"
    replies = [item for item in result.events if isinstance(item, ToolCallFinishedEvent)]
    assert len(replies) == 1
    assert replies[0].result.is_error
    assert not any(isinstance(item, ActionStartedEvent) for item in result.events)


async def test_facade_manages_wrapped_native_model_context_on_reuse(site, monkeypatch):
    native = pytest.importorskip("pydantic_ai.models.test")
    model = native.TestModel(call_tools=[], custom_output_text="Native model adapted")
    enter, leave = AsyncMock(return_value=model), AsyncMock()
    monkeypatch.setattr(native.TestModel, "__aenter__", enter)
    monkeypatch.setattr(native.TestModel, "__aexit__", leave)
    agent = BrowserAgent(model=PydanticAIModel(model), browser=LaunchBrowser(url=site))
    result = await agent.run("Inspect the page")
    assert result.text == "Native model adapted"
    assert model.last_model_request_parameters is not None
    assert enter.await_count == leave.await_count > 0
    first_contexts = enter.await_count
    assert (await agent.run("Inspect again")).text == "Native model adapted"
    assert enter.await_count == leave.await_count > first_contexts
