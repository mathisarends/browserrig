import asyncio
import io
import json

import pytest
import yaml
from harnessed import Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ModelRequestedEvent, ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel

from browserrig import (
    Actions,
    Browser,
    BrowserAgent,
    CanvasMode,
    DomMode,
    LaunchBrowser,
    TerminalEvents,
)
from browserrig.events import CursorMovedEvent, CursorStateEvent, InputEvent

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("canvas", [False, True])
async def test_typing_shortcuts_stream_and_storage(site, tmp_path, canvas):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, browser: Inject[Browser]):
            holder["browser"] = browser

    directory = tmp_path / "sessions"
    agent = BrowserAgent(
        model=_typing_model(holder, canvas),
        browser=LaunchBrowser(url=site),
        mode=CanvasMode(selector="html") if canvas else DomMode(),
        session_directory=directory,
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[TerminalEvents(output), Access()],
    )
    async with agent.session() as session:
        streamed = []
        # Subscribe before run; opening an async generator alone does not register it.
        ready = asyncio.Event()

        consumer = asyncio.create_task(_consume(session, streamed, ready))
        await ready.wait()
        result = await session.run("Type exactly and use shortcuts", max_steps=10)
        assert result.text == "Done"
        receipts = [e for e in session.events if isinstance(e, ToolExecutionFinishedEvent)]
        assert all(not receipt.result.is_error for receipt in receipts)
        tab = holder["browser"].active_tab
        assert await tab.evaluate("document.querySelector('#email').value") == "+"
        assert await tab.evaluate("document.querySelector('#secret').value") == "Secret!"
        assert not any(isinstance(event, InputEvent) for event in session.events)
    await consumer
    _assert_events(streamed, output.getvalue(), directory, canvas)


def _typing_model(holder, canvas):
    text = "Grüße + 🙂"
    shortcut = ToolCall("send_keys", {"key": "a", "hold_control": True})
    if canvas:
        calls = [
            ToolCall("click_at", {"x": 80, "y": 18}),
            ToolCall("send_keys", {"text": text}),
            shortcut,
            ToolCall("send_keys", {"key": "+"}),
            ToolCall("click_at", {"x": 320, "y": 18}),
            ToolCall("send_keys", {"key": "a", "hold_control": True}),
            ToolCall("send_keys", {"text": "Secret!"}),
        ]
    else:
        calls = [
            lambda request: ToolCall(
                "type_text", {"ref": _ref(request, "Email"), "text": "old value"}
            ),
            lambda request: ToolCall("type_text", {"ref": _ref(request, "Email"), "text": text}),
            shortcut,
            ToolCall("send_keys", {"key": "+"}),
            lambda request: ToolCall(
                "type_text", {"ref": _ref(request, "Password"), "text": "Secret!"}
            ),
        ]
    step = 0

    async def respond(request):
        nonlocal step
        tools = {tool.name: tool for tool in request.tools}
        assert "press_key" not in tools
        assert ("type_text" in tools) != canvas
        assert set(tools["send_keys"].parameters["properties"]) == {
            "text",
            "key",
            "hold_control",
            "hold_shift",
            "hold_alt",
            "hold_meta",
        }
        if step == 2:
            assert (
                await holder["browser"].active_tab.evaluate(
                    "document.querySelector('#email').value"
                )
                == text
            )
        if step < len(calls):
            call = calls[step]
            yield ModelChunk(tool_call=call(request) if callable(call) else call)
        else:
            yield ModelChunk(text="Done")
        step += 1

    return CallbackModel(respond)


async def _consume(session, streamed, ready):
    ready.set()
    async for event in session.subscribe(transient=True):
        streamed.append(event)


def _assert_events(streamed, output, directory, canvas):
    live = [event for event in streamed if isinstance(event, InputEvent)]
    assert live and all(event.browser_id and event.target_id for event in live)
    assert all(event.action_id or isinstance(event, CursorStateEvent) for event in live)
    keys = [event for event in live if event.type == "browser.key.pressed"]
    assert [event.key for event in keys][-7:] == list("Secret!")
    assert keys[-7].modifiers == ("Shift",)
    records = [json.loads(line) for line in output.splitlines()]
    assert any(record["type"] == "browser.cursor.moved" for record in records)
    assert any(record["type"] == "browser.pointer.pressed" for record in records) == canvas
    assert [record["key"] for record in records if record["type"] == "browser.key.pressed"] == [
        event.key for event in keys
    ]
    files = list(directory.rglob("*.jsonl"))
    assert files
    for path in files:
        stored = path.read_text(encoding="utf-8")
        assert '"browser.key.pressed"' not in stored
        assert '"browser.cursor.moved"' not in stored


async def test_turn_start_publishes_initial_cursor_before_any_model_or_input_action(site):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, browser: Inject[Browser]):
            holder["browser"] = browser

    agent = BrowserAgent(
        model=ScriptedModel(["First", "Second"]),
        browser=LaunchBrowser(url=site),
        plugins=[TerminalEvents(output), Access()],
    )
    async with agent.session() as session:
        streamed = []
        ready = asyncio.Event()
        consumer = asyncio.create_task(_consume(session, streamed, ready))
        await ready.wait()
        tab = holder["browser"].active_tab
        position = tab.mouse.position
        width, height = await tab.evaluate("[innerWidth, innerHeight]")
        assert 0.35 * width <= position.x <= 0.65 * width
        assert 0.35 * height <= position.y <= 0.65 * height
        await session.run("Inspect without moving")
        await session.run("Continue without moving")
        assert tab.mouse.position == position
        assert not any(isinstance(event, InputEvent) for event in session.events)
    await consumer
    states = [event for event in streamed if isinstance(event, CursorStateEvent)]
    assert len(states) == 2
    assert all((event.x, event.y) == (position.x, position.y) for event in states)
    assert all(
        event.browser_id and event.target_id == tab.id and not event.action_id for event in states
    )
    assert not any(isinstance(event, CursorMovedEvent) for event in streamed)
    first_cursor = next(
        index for index, event in enumerate(streamed) if isinstance(event, CursorStateEvent)
    )
    first_model = next(
        index for index, event in enumerate(streamed) if isinstance(event, ModelRequestedEvent)
    )
    assert first_cursor < first_model
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    cursor = next(record for record in records if record["type"] == "browser.cursor.state")
    assert (cursor["x"], cursor["y"]) == (position.x, position.y)


def _ref(request, name):
    state = next(
        yaml.safe_load(message.text)
        for message in reversed(request.messages)
        if message.text.startswith("page:\n")
    )
    return next(element["ref"] for element in state["elements"] if element["name"] == name)


async def test_element_highlight_uses_live_bounds_after_scroll(site):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions

    agent = BrowserAgent(
        model=ScriptedModel(["Observed"]),
        browser=LaunchBrowser(url=site),
        plugins=[TerminalEvents(output), Access()],
    )
    async with agent.session() as session:
        await session.run("Observe")
        actions = holder["actions"]
        tab = actions.browser.active_tab
        ref = next(
            element.ref for element in actions.observe.snapshot.elements if element.name == "Email"
        )
        await tab.evaluate(
            "Object.assign(document.querySelector('#email').style, "
            "{position:'absolute',top:'1800px',left:'30px'})"
        )
        point = await actions.element_point(tab=tab, ref=ref)
        actual = await tab.evaluate(
            "(() => { const r = document.querySelector('#email').getBoundingClientRect();"
            "return {x:r.x,y:r.y,width:r.width,height:r.height}; })()"
        )
        assert point.scrolled
        assert point.bounds.model_dump() == actual
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    highlight = next(
        record for record in records if record["type"] == "browser.element.highlighted"
    )
    assert {key: highlight[key] for key in actual} == actual
