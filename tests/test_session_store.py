import asyncio

import pytest
from harnessed import Observation, PolicyDecision
from harnessed.errors import ConfigError
from harnessed.events import (
    AgentControlChangedEvent,
    ControlState,
    OutputValidatedEvent,
    ToolCallFinishedEvent,
)
from harnessed.integrations.json import JsonSessionStore
from harnessed.models import ImageReference, ModelChunk, TextPart
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel, call
from pydantic import BaseModel

from browserrig import Activity, Agent, Done, browser_plugins
from browserrig.events import ActivityFinishedEvent


class Answer(BaseModel):
    title: str


def _agent(model, *, store=None, plugins=()):
    # Exercise the facade and real Activity/Done plugins without launching Chrome.
    return Agent(
        model=model,
        store=store,
        plugins=plugins,
        without=tuple(
            type(plugin)
            for plugin in browser_plugins()
            if not isinstance(plugin, Activity)
        ),
    )


async def test_facade_reopens_history_context_and_image_assets_with_a_new_store(
    tmp_path,
):
    root = tmp_path / "sessions"
    store = JsonSessionStore(root=root)
    agent = _agent(ScriptedModel(["First answer"]), store=store)
    assert not root.exists()
    async with agent.session(id="conversation") as session:
        image = await session.assets.put(b"screenshot", media_type="image/png")
        await session.context.set("task", "Remember the page")
        session.observe(
            Observation(
                source="browser",
                content=(TextPart("Page content"), ImageReference(image)),
            )
        )
        assert (await session.run("Inspect")).text == "First answer"
        await session.flush()
    saved = await store.load_session("conversation")
    assert saved is not None and saved.revision > 0
    assert saved.checkpoint.version == 2

    model = ScriptedModel(["Continued answer"])
    reopened = _agent(model, store=JsonSessionStore(root=root))
    async with reopened.session(id="conversation") as session:
        assert session.id == "conversation"
        assert await session.assets.read(image) == b"screenshot"
        assert session.context.values["task"] == "Remember the page"
        assert (await session.run("Continue")).text == "Continued answer"
    messages = model.requests[-1].messages
    assert any("First answer" in message.text for message in messages)
    assert any("Page content" in message.text for message in messages)


async def test_facade_keeps_ephemeral_sessions_and_explicit_state_continuation():
    model = ScriptedModel(["First answer", "Continued answer"])
    agent = _agent(model)
    async with agent.session() as session:
        first_id = session.id
        first = await session.run("Inspect")
        await session.flush()
    async with agent.session(state=first.state) as session:
        assert session.id != first_id
        assert (await session.run("Continue")).text == "Continued answer"
    assert any(
        "First answer" in message.text for message in model.requests[-1].messages
    )
    with pytest.raises(ConfigError, match="requires an explicit store"):
        async with agent.session(id="conversation"):
            pytest.fail("Opening by ID needs a store")


async def test_paused_done_restores_browser_events_and_structured_finalization(
    tmp_path,
):
    entered, release, pausing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def done_response(_request):
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        yield ModelChunk(tool_call=call("done", success=True).message.tool_calls[0])

    def control_changed(event):
        if event.state is ControlState.PAUSING:
            pausing.set()

    root = tmp_path / "sessions"
    agent = _agent(
        CallbackModel(done_response),
        store=JsonSessionStore(root=root),
        plugins=[Done(), Approvals(default=PolicyDecision.ALLOW)],
    )
    async with agent.session(id="paused") as session:
        session.on(AgentControlChangedEvent, control_changed)
        await session.submit("Return the title", output=Answer, max_steps=3)
        await asyncio.wait_for(entered.wait(), 5)
        pause = asyncio.create_task(session.pause())
        try:
            await asyncio.wait_for(pausing.wait(), 5)
        finally:
            release.set()
        await asyncio.wait_for(pause, 5)
        assert session.log.control.state is ControlState.PAUSED
        assert session.last(ToolCallFinishedEvent).call.name == "done"

    model = ScriptedModel([call("final_answer", title="Restored title")])
    reopened = _agent(
        model,
        store=JsonSessionStore(root=root),
        plugins=[Done(), Approvals(default=PolicyDecision.ALLOW)],
    )
    async with reopened.session(id="paused", restore_outputs=[Answer]) as session:
        assert session.log.control.state is ControlState.PAUSED
        assert session.last(ToolCallFinishedEvent).call.name == "done"
        assert session.last(ActivityFinishedEvent) is not None
        await session.resume()
        await asyncio.wait_for(session.wait_until_idle(), 5)
        assert session.last(OutputValidatedEvent).data == {"title": "Restored title"}
    assert len(model.requests) == 1
    assert [tool.name for tool in model.requests[0].tools] == ["final_answer"]
