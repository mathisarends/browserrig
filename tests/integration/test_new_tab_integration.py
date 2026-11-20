import asyncio

import pytest
from harnessed.models import ModelChunk, ToolCall, ToolMessage
from harnessed.testing import CallbackModel, ScriptedModel

from browserrig import (
    Agent,
    Browser,
    BrowserCoordination,
    Choreography,
    Chrome,
    Input,
    Point,
    SingleTab,
    wait_for_page,
)
from browserrig.choreography import TabPressedEvent
from browserrig.events import (
    KeyPressedEvent,
    TabActivatedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)
from tests.javascript import evaluate
from tests.observations import all_states

pytestmark = pytest.mark.integration


async def _click(site, name, *, path="/links", tab_mode=None, **arguments):
    """Click the element called `name`; return what the agent saw next and
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
        browser=Chrome.launch(url=site + path),
        plugins=[Choreography(), tab_mode],
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
    assert not any(isinstance(event, TabPressedEvent) for event in events)
    assert [
        event.target_id for event in events if isinstance(event, TabActivatedEvent)
    ] == [opened[0].target_id]


async def test_click_on_window_open_follows_into_the_loaded_tab(site):
    seen, events = await _click(site, "New tab", path="/")
    (opened,) = [event for event in events if isinstance(event, TabOpenedEvent)]
    assert seen["page"]["tab"] == opened.target_id != seen["first_tab"]
    assert seen["page"]["url"] == site + "/other"
    assert not any(isinstance(event, TabPressedEvent) for event in events)


async def test_delayed_foreground_popup_returns_control_to_opener_on_close(site):
    model = ScriptedModel(["Back on the opener"])
    agent = Agent(model=model, browser=Chrome.launch(url=site + "/links"))
    activated = asyncio.Event()
    closed = asyncio.Event()

    async def on_activation(_event: TabActivatedEvent) -> None:
        activated.set()

    async def on_close(_event: TabClosedEvent) -> None:
        closed.set()

    async with agent.session() as session:
        browser = session.scope[Browser]
        coordination = session.scope[BrowserCoordination]
        opener = browser.active_tab
        session.scope.on(TabActivatedEvent, on_activation)
        session.scope.on(TabClosedEvent, on_close)
        async with coordination.exclusive():
            mark = browser.tabs.openings
            await evaluate(opener, "setTimeout(() => window.open('/other'), 50)")
            child = await browser.tabs.opened_since(mark, timeout_seconds=5)
            assert child is not None and child is not opener
            assert browser.active_tab is opener and not activated.is_set()
        async with asyncio.timeout(5):
            await activated.wait()
        assert browser.active_tab is child
        assert await evaluate(child, "document.hasFocus() && !document.hidden") is True

        activated.clear()
        await evaluate(child, "setTimeout(() => window.close(), 0)")
        async with asyncio.timeout(5):
            await closed.wait()
        await session.run("Inspect the current tab", max_steps=3)
        assert all_states(model.requests[0].messages)[-1]["page"]["tab"] == opener.id
        async with asyncio.timeout(5):
            await activated.wait()
        assert browser.active_tab is opener
        assert await evaluate(opener, "document.hasFocus() && !document.hidden") is True


async def test_native_background_tab_keeps_the_opener_active(site):
    agent = Agent(model=ScriptedModel([]), browser=Chrome.launch(url=site + "/links"))
    activated = asyncio.Event()

    async def on_activation(_event: TabActivatedEvent) -> None:
        activated.set()

    async with agent.session() as session:
        browser = session.scope[Browser]
        devices = session.scope[Input]
        opener = browser.active_tab
        session.scope.on(TabActivatedEvent, on_activation)
        await wait_for_page(opener)
        x, y = await evaluate(
            opener,
            """(() => {
            const link = document.querySelector('a').getBoundingClientRect();
            return [link.x + link.width / 2, link.y + link.height / 2];
        })()""",
        )
        mark = browser.tabs.openings
        key = await browser.tabs.link_modifier()
        async with devices.keyboard.hold(key) as modifiers:
            await devices.mouse.click(Point(x=x, y=y), modifiers=modifiers)
        child = await browser.tabs.opened_since(mark, timeout_seconds=5)
        assert child is not None and child is not opener
        assert await evaluate(child, "document.hidden") is True
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1.25):
                await activated.wait()
        assert browser.active_tab is opener


async def test_click_without_new_tab_parameter_follows_link_in_single_tab(site):
    seen, events = await _click(site, "Blank link", tab_mode=SingleTab())
    assert seen["page"]["tab"] == seen["first_tab"]
    assert seen["page"]["url"] == site + "/other"
    assert not any(isinstance(event, TabOpenedEvent) for event in events)


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
    assert keys[0].key == "Shift"
    assert keys[0].modifiers in {("Control",), ("Meta",)}
    assert not any(isinstance(event, TabPressedEvent) for event in events)


async def test_new_tab_click_without_a_link_stays_in_the_tab(site):
    seen, events = await _click(site, "Plain button", new_tab=True)
    assert not [event for event in events if isinstance(event, TabOpenedEvent)]
    assert seen["page"]["tab"] == seen["first_tab"]
    assert "No new tab opened" in seen["reply"]
