from unittest.mock import AsyncMock

import pytest
from harnessed import Agent as HarnessedAgent
from harnessed import Plugin, PolicyDecision, SessionState
from harnessed.events import TextDeltaEvent, ToolCallFinishedEvent, TurnResultEvent
from harnessed.integrations.json import JsonSessionStore
from harnessed.kernel import Scope, needs
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call
from pydantic import BaseModel

from browserrig import Agent, Browser, Chrome, ChromeBrowser, Done
from browserrig.events import ActionStartedEvent, ActivityStartedEvent
from browserrig.kinds import ActivityKind

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("existing_tab", [False, True])
async def test_connect_plugin_disconnects_without_stopping_external_browser(
    manual, existing_tab
):
    connections = []

    class Access(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _ctx: Scope):
            browser = self._setup_browser
            connections.append(browser)

    async with ChromeBrowser() as owner:
        original = owner.active_tab
        plugin = Chrome.connect(
            endpoint=owner.client.transport.url,
            target_id=original.id if existing_tab else None,
        )
        model = ScriptedModel([])
        agent = (
            HarnessedAgent(model=model, plugins=[plugin, Access()])
            if manual
            else Agent(model=model, browser=plugin, plugins=[Access()])
        )
        async with agent.session():
            connected = connections[0]
            target = connected.active_tab.id
            assert connected.client.is_connected
            assert (target == original.id) is existing_tab
        assert not connected.client.is_connected
        assert owner.client.is_connected
        assert await original.cdp.runtime.evaluate(expression="1 + 1")
        targets = {tab.id for tab in await owner.tabs.list()}
        assert original.id in targets
        assert (target in targets) is existing_tab


@pytest.mark.parametrize("persistent", [False, True])
async def test_facade_restores_saved_state_and_owns_a_fresh_browser_per_session(
    site, tmp_path, persistent
):
    browsers = []

    class Access(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _ctx: Scope):
            browser = self._setup_browser
            browsers.append(browser)

    model = ScriptedModel(["First answer", "Restored answer"])
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[Access()],
        store=JsonSessionStore(root=tmp_path / "sessions") if persistent else None,
    )
    async with agent.session(id="browser" if persistent else None) as session:
        first = await session.run("Remember this page")
        assert first.text == "First answer"
        saved = first.state.to_json()
    assert not browsers[0].client.is_connected
    async with agent.session(
        id="browser" if persistent else None,
        state=None if persistent else SessionState.from_json(saved),
    ) as session:
        second = await session.run("Continue the conversation")
        assert second.text == "Restored answer"
        assert any("First answer" in msg.text for msg in model.requests[-1].messages)
    # Each session mounts its own Activity, so model intervals carry a new epoch.
    epochs = {
        item.epoch_id
        for item in (*first.events, *second.events)
        if isinstance(item, ActivityStartedEvent) and item.kind is ActivityKind.LLM
    }
    assert len(epochs) == 2
    assert len(browsers) == 2
    assert browsers[0].id != browsers[1].id
    assert not browsers[1].client.is_connected


async def test_facade_honors_explicit_tool_policy(site):
    model = ScriptedModel([call("navigate", url=site + "/other"), "Denied"])
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW, deny=["navigate"])],
    )
    result = await agent.run("Try navigation")
    assert result.text == "Denied"
    replies = [
        item for item in result.events if isinstance(item, ToolCallFinishedEvent)
    ]
    assert len(replies) == 1
    assert replies[0].result.is_error
    assert not any(isinstance(item, ActionStartedEvent) for item in result.events)


async def test_facade_manages_wrapped_native_model_context_on_reuse(site, monkeypatch):
    native = pytest.importorskip("pydantic_ai.models.test")
    model = native.TestModel(call_tools=[], custom_output_text="Native model adapted")
    enter, leave = AsyncMock(return_value=model), AsyncMock()
    monkeypatch.setattr(native.TestModel, "__aenter__", enter)
    monkeypatch.setattr(native.TestModel, "__aexit__", leave)
    agent = Agent(model=PydanticAIModel(model), browser=Chrome.launch(url=site))
    result = await agent.run("Inspect the page")
    assert result.text == "Native model adapted"
    assert model.last_model_request_parameters is not None
    assert enter.await_count == leave.await_count > 0
    first_contexts = enter.await_count
    assert (await agent.run("Inspect again")).text == "Native model adapted"
    assert enter.await_count == leave.await_count > first_contexts


async def test_facade_streams_commentary_and_returns_a_typed_answer_after_done(site):
    class PageAnswer(BaseModel):
        title: str
        url: str

    model = ScriptedModel(
        [
            "I will open the other page.",
            call("navigate", url=site + "/other"),
            "The other page is open.",
            call("done", success=True),
            call("final_answer", title="Other", url=site + "/other"),
        ]
    )
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW), Done()],
    )
    async with (
        agent.session() as session,
        session.stream(
            "Open the other page and report its title and URL.",
            output=PageAnswer,
            max_steps=5,
        ) as run,
    ):
        events = [event async for event in run]
    assert [event.text for event in events if isinstance(event, TextDeltaEvent)] == [
        "I will open the other page.",
        "The other page is open.",
    ]
    assert isinstance(events[-1], TurnResultEvent)
    result = events[-1].result
    assert result.completed
    assert result.output == PageAnswer(title="Other", url=site + "/other")
    assert any(isinstance(event, ActionStartedEvent) for event in result.events)
    # Browser tools stay declared after done; only the output tool joins them.
    assert [tool.name for tool in model.requests[-1].tools] == [
        *(tool.name for tool in model.requests[0].tools),
        "final_answer",
    ]
