import asyncio

import pytest
from harnessed import PolicyDecision
from harnessed.errors import ConfigError
from harnessed.events import (
    ControlState,
    OutputValidatedEvent,
    SessionControlChangedEvent,
    ToolCallFinishedEvent,
)
from harnessed.integrations.json import JsonSessionStore
from harnessed.models import ImageReference, ModelChunk, TextPart, UserMessage
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


@pytest.mark.parametrize("persistent", [False, True])
async def test_facade_adds_context_without_a_turn_and_restores_duplicate_messages(
    tmp_path, persistent
):
    store = JsonSessionStore(root=tmp_path / "sessions") if persistent else None
    model = ScriptedModel(["Continued"])
    agent = _agent(model, store=store)
    async with agent.session(id="context" if persistent else None) as session:
        for text in ("Include source URLs.", "Keep it brief.", "Include source URLs."):
            await session.append_message(UserMessage(text))
        messages = list(session.messages)
        assert all(isinstance(message, UserMessage) for message in messages)
        assert [message.text for message in messages] == [
            "Include source URLs.",
            "Keep it brief.",
            "Include source URLs.",
        ]
        assert len({message.id for message in messages}) == 3
        assert not model.requests and not session.inbox.pending
        assert session.log.open_turn is None
        state = session.snapshot()
        if store is not None:
            saved = await store.load_session("context")
            assert saved is not None
            assert saved.checkpoint.state.history == state.history

    async with agent.session(
        id="context" if persistent else None,
        state=None if persistent else state,
    ) as session:
        assert list(session.messages) == messages
        assert (await session.run("Continue")).text == "Continued"
    assert len(model.requests) == 1
    assert [
        message
        for message in model.requests[0].messages
        if isinstance(message, UserMessage)
    ][:3] == messages


async def test_context_added_during_a_request_is_used_by_the_next_turn():
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(_request):
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        yield ModelChunk(text="Answer")

    model = CallbackModel(respond)
    agent = _agent(model)
    async with agent.session() as session:
        handle = await session.submit("Inspect")
        await asyncio.wait_for(entered.wait(), 5)
        try:
            await session.append_message(UserMessage("Use metric units."))
            assert all(
                message.text != "Use metric units."
                for message in model.requests[0].messages
            )
        finally:
            release.set()
        assert (await handle.result()).text == "Answer"
        assert (await session.run("Continue")).text == "Answer"
    assert len(model.requests) == 2
    assert any(
        message.text == "Use metric units." for message in model.requests[1].messages
    )


async def test_facade_reopens_history_context_and_image_assets_with_a_new_store(
    tmp_path,
):
    root = tmp_path / "sessions"
    store = JsonSessionStore(root=root)
    initial_model = ScriptedModel(["First answer"])
    agent = _agent(initial_model, store=store)
    assert not root.exists()
    async with agent.session(id="conversation") as session:
        image = await session.assets.put(b"screenshot", media_type="image/png")
        await session.append_message(UserMessage("Remember the page"))
        assert not initial_model.requests
        assert not session.inbox.pending
        session.observe(
            UserMessage(
                content=(TextPart("Page content"), ImageReference(image)),
            ),
            source="browser",
        )
        assert (await session.run("Inspect")).text == "First answer"
        await session.flush()
    saved = await store.load_session("conversation")
    assert saved is not None and saved.revision > 0
    assert saved.checkpoint.version == 3

    model = ScriptedModel(["Continued answer"])
    reopened = _agent(model, store=JsonSessionStore(root=root))
    async with reopened.session(id="conversation") as session:
        assert session.id == "conversation"
        assert await session.assets.read(image) == b"screenshot"
        assert any(message.text == "Remember the page" for message in session.messages)
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
        session.on(SessionControlChangedEvent, control_changed)
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
    # Working tools stay declared after done; only the output tool joins them.
    assert [tool.name for tool in model.requests[0].tools] == ["done", "final_answer"]
