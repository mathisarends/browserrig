import asyncio

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.models import ModelChunk, ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Agent, Chrome, InputVisualization
from browserrig.events import KeyPressedEvent, TabOpenedEvent
from tests.observations import all_states

pytestmark = pytest.mark.integration


async def _click(site, name, **arguments):
    """Click the element called `name` on /links; return what the agent saw next and
    every event, including those only streamed to viewers.
    """
    seen = {}

    async def respond(request):
        state = all_states(request.messages)[-1]
        replies = [m for m in request.messages if isinstance(m, ToolMessage)]
        if not replies:
            seen["first_tab"] = state["page"]["tab"]
            element = next((e for e in state["elements"] if e["name"] == name), None)
            assert element is not None, f"Missing link: {name}"
            yield ModelChunk(
                tool_call=ToolCall("click", {"ref": element["ref"], **arguments})
            )
            return
        seen["reply"] = replies[-1].text
        seen["page"] = state["page"]
        seen["nudges"] = [m.text for m in request.messages if "nudges" in m.text]
        yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site + "/links"),
        plugins=[Approvals(default=PolicyDecision.ALLOW), InputVisualization()],
    )
    streamed = []
    ready = asyncio.Event()

    async def consume(session):
        ready.set()
        async for event in session.subscribe(transient=True):
            streamed.append(event)

    async with agent.session() as session:
        consumer = asyncio.create_task(consume(session))
        await asyncio.wait_for(ready.wait(), 30)
        await session.run("Click", max_steps=3)
    await asyncio.wait_for(consumer, 30)
    return seen, streamed


async def test_click_on_a_target_blank_link_follows_into_the_loaded_tab(site):
    seen, events = await _click(site, "Blank link")
    opened = [event for event in events if isinstance(event, TabOpenedEvent)]
    assert len(opened) == 1
    assert seen["page"]["tab"] == opened[0].target_id != seen["first_tab"]
    assert seen["page"]["url"] == site + "/other"
    assert f"It opened tab {opened[0].target_id}, which is now active" in seen["reply"]
    assert seen["first_tab"] in seen["reply"]
    assert not any("A tab opened" in text for text in seen["nudges"])
    assert not any(isinstance(event, KeyPressedEvent) for event in events)


async def test_new_tab_click_holds_the_link_modifier_and_follows(site):
    seen, events = await _click(site, "Plain link", new_tab=True)
    opened = [event for event in events if isinstance(event, TabOpenedEvent)]
    assert len(opened) == 1
    assert seen["page"]["tab"] == opened[0].target_id
    assert seen["page"]["url"] == site + "/other"
    assert seen["reply"].startswith("New-tab click dispatched. It opened tab")
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert [(key.key, key.target_id) for key in keys] == [
        (keys[0].key, seen["first_tab"])
    ]
    assert keys[0].key in {"Control", "Meta"}


async def test_new_tab_click_without_a_link_stays_in_the_tab(site):
    seen, events = await _click(site, "Plain button", new_tab=True)
    assert not [event for event in events if isinstance(event, TabOpenedEvent)]
    assert seen["page"]["tab"] == seen["first_tab"]
    assert "No new tab opened" in seen["reply"]
