from unittest.mock import AsyncMock

import pytest
from harnessed import Context, Inject, Plugin, PolicyDecision, SessionState
from harnessed.events import ToolCallFinishedEvent
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Browser, BrowserAgent, LaunchBrowser
from browserrig.events import ActionStartedEvent, ActivityStartedEvent
from browserrig.kinds import ActivityKind

pytestmark = pytest.mark.integration


async def test_facade_continues_explicit_state_and_owns_a_fresh_browser_per_session(site, tmp_path):
    browsers = []

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            browsers.append(browser)

    model = ScriptedModel(["First answer", "Restored answer", "Independent answer"])
    agent = BrowserAgent(
        model=model,
        browser=LaunchBrowser(url=site),
        plugins=[Access()],
    )
    async with agent.session() as session:
        first_id = session.id
        first = await session.run("Remember this page")
        assert first.text == "First answer"
        assert session.snapshot() == first.state
        assert first.events and not session.events
    assert not browsers[0].client.is_connected
    state_file = tmp_path / "conversation.json"
    state_file.write_text(first.state.to_json(), encoding="utf-8")
    state = SessionState.from_json(state_file.read_text(encoding="utf-8"))
    original_payload = state.to_json()
    async with agent.session(state=state) as session:
        assert session.id != first_id
        second = await session.run("Continue the conversation")
        assert second.text == "Restored answer"
        assert any("First answer" in msg.text for msg in model.requests[-1].messages)
        epochs = {
            item.epoch_id
            for item in second.events
            if isinstance(item, ActivityStartedEvent) and item.kind is ActivityKind.LLM
        }
        assert len(epochs) == 1
    independent = await agent.run("Explore another approach", state=state)
    assert independent.text == "Independent answer"
    assert "First answer" in repr(model.requests[-1].messages)
    assert "Restored answer" not in repr(model.requests[-1].messages)
    assert "Continue the conversation" not in repr(model.requests[-1].messages)
    assert state.to_json() == original_payload
    assert len(browsers) == 3 and len({browser.id for browser in browsers}) == 3
    assert all(not browser.client.is_connected for browser in browsers)


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
