import asyncio
import io
import json

import pytest
from harnessed import Plugin, PolicyDecision, ToolCall
from harnessed.events import ModelRequestedEvent, ToolExecutionFinishedEvent
from harnessed.kernel import needs
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel
from harnessed.testing import call as scripted_call

from browserrig import (
    Actions,
    Agent,
    Browser,
    Chrome,
    TerminalEvents,
)
from browserrig.events import CursorMovedEvent, CursorStateEvent, InputEvent
from tests.javascript import evaluate
from tests.observations import latest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("coordinates", [False, True])
async def test_typing_shortcuts_stream_and_storage(site, coordinates):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self):
            browser = self._setup_browser
            holder["browser"] = browser

    agent = Agent(
        model=_typing_model(holder, coordinates),
        browser=Chrome.launch(url=site),
        plugins=[
            Approvals(default=PolicyDecision.ALLOW),
            TerminalEvents(output),
            Access(),
        ],
    )
    async with agent.session() as session:
        streamed = []
        # Subscribe before run; opening an async generator alone does not register it.
        ready = asyncio.Event()

        consumer = asyncio.create_task(_consume(session, streamed, ready))
        await asyncio.wait_for(ready.wait(), 30)
        result = await session.run("Type exactly and use shortcuts", max_steps=10)
        assert result.text == "Done"
        receipts = [
            e for e in result.events if isinstance(e, ToolExecutionFinishedEvent)
        ]
        assert all(not receipt.result.is_error for receipt in receipts)
        tab = holder["browser"].active_tab
        assert await evaluate(tab, "document.querySelector('#email').value") == "+"
        assert (
            await evaluate(tab, "document.querySelector('#secret').value") == "Secret!"
        )
        assert not any(isinstance(event, InputEvent) for event in result.events)
        stored = session.snapshot().to_json()
    await asyncio.wait_for(consumer, 30)
    _assert_events(streamed, output.getvalue(), stored, coordinates)


async def test_turn_start_publishes_initial_cursor_before_any_model_or_input_action(
    site,
):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self):
            browser = self._setup_browser
            holder["browser"] = browser

    agent = Agent(
        model=ScriptedModel(["First", "Second"]),
        browser=Chrome.launch(url=site),
        plugins=[TerminalEvents(output), Access()],
    )
    async with agent.session() as session:
        streamed = []
        ready = asyncio.Event()
        consumer = asyncio.create_task(_consume(session, streamed, ready))
        await asyncio.wait_for(ready.wait(), 30)
        tab = holder["browser"].active_tab
        position = holder["browser"].input.mouse.position
        width, height = await evaluate(tab, "[innerWidth, innerHeight]")
        assert 0.35 * width <= position.x <= 0.65 * width
        assert 0.35 * height <= position.y <= 0.65 * height
        first = await session.run("Inspect without moving")
        second = await session.run("Continue without moving")
        assert holder["browser"].input.mouse.position == position
        events = (*first.events, *second.events)
        assert not any(isinstance(event, InputEvent) for event in events)
    await asyncio.wait_for(consumer, 30)
    states = [event for event in streamed if isinstance(event, CursorStateEvent)]
    assert len(states) == 2
    assert all((event.x, event.y) == (position.x, position.y) for event in states)
    assert all(
        event.browser_id and event.target_id == tab.id and not event.action_id
        for event in states
    )
    assert not any(isinstance(event, CursorMovedEvent) for event in streamed)
    first_cursor = next(
        index
        for index, event in enumerate(streamed)
        if isinstance(event, CursorStateEvent)
    )
    first_model = next(
        index
        for index, event in enumerate(streamed)
        if isinstance(event, ModelRequestedEvent)
    )
    assert first_cursor < first_model
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    cursor = next(
        record for record in records if record["type"] == "browser.cursor.state"
    )
    assert (cursor["x"], cursor["y"]) == (position.x, position.y)


@pytest.mark.parametrize("coordinates", [False, True])
async def test_move_mouse_hovers_and_scrolls_only_the_target_panel(site, coordinates):
    holder = {}

    class Panels(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self):
            browser = self._setup_browser
            holder["browser"] = browser
            tab = holder["tab"] = browser.active_tab
            await evaluate(
                tab,
                """document.body.innerHTML = `<style>
                    body{margin:0;height:2200px}
                    .panel{position:absolute;top:80px;width:200px;height:240px;overflow:auto}
                    #first{left:20px}#second{left:320px}
                    .content{height:1600px;
                        background:repeating-linear-gradient(white 0 40px,steelblue 40px 80px)}
                    </style><div id=first class=panel><div class=content>First</div></div>
                    <div id=second class=panel><div class=content>Second</div></div>`;
                    window.clicks=0;window.hovered=[];
                    document.addEventListener('click',()=>window.clicks++);
                    document.querySelectorAll('.panel').forEach(panel=>{
                        panel.addEventListener('mouseenter',()=>window.hovered.push(panel.id))
                    });""",
            )

    # Exercise both a zoomed crop and viewport coordinates.
    requests = (
        []
        if coordinates
        else [
            scripted_call(
                "screenshot",
                region={"x": 20, "y": 80, "width": 500, "height": 240},
                zoom=2,
            )
        ]
    )
    requests.extend(
        [
            scripted_call("move_mouse", x=70 if coordinates else 100, y=160),
            scripted_call("scroll", delta_y=300),
            scripted_call("move_mouse", x=370 if coordinates else 700, y=160),
            scripted_call("scroll", delta_y=180),
            "Done",
        ]
    )
    agent = Agent(
        model=ScriptedModel(requests),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW), Panels()],
    )
    async with agent.session() as session:
        result = await session.run(
            "Hover and scroll each panel without clicking", max_steps=6
        )
        assert result.text == "Done"
        receipts = [
            e for e in result.events if isinstance(e, ToolExecutionFinishedEvent)
        ]
        assert receipts and all(not receipt.result.is_error for receipt in receipts)
        state = await evaluate(
            holder["tab"],
            "({first:document.querySelector('#first').scrollTop,"
            "second:document.querySelector('#second').scrollTop,page:scrollY,"
            "clicks:window.clicks,hovered:window.hovered})",
        )
        assert state["first"] == pytest.approx(300, abs=1)
        assert state["second"] == pytest.approx(180, abs=1)
        assert state["page"] == 0 and state["clicks"] == 0
        assert {"first", "second"} <= set(state["hovered"])
        assert holder["browser"].input.mouse.position.x == pytest.approx(370)
        assert holder["browser"].input.mouse.position.y == pytest.approx(160)


async def test_element_highlight_uses_live_bounds_after_scroll(site):
    holder = {}
    output = io.StringIO()

    class Access(Plugin, needs=(Actions,)):
        _setup_actions = needs(Actions)

        async def setup(self):
            actions = self._setup_actions
            holder["actions"] = actions

    agent = Agent(
        model=ScriptedModel(["Observed"]),
        browser=Chrome.launch(url=site),
        plugins=[TerminalEvents(output), Access()],
    )
    async with agent.session() as session:
        await session.run("Observe")
        actions = holder["actions"]
        tab = actions.browser.active_tab
        ref = next(
            element.ref
            for element in actions.observe.snapshot.elements
            if element.name == "Email"
        )
        await evaluate(
            tab,
            "Object.assign(document.querySelector('#email').style, "
            "{position:'absolute',top:'1800px',left:'30px'})",
        )
        point = await actions.element_point(tab=tab, ref=ref)
        actual = await evaluate(
            tab,
            "(() => { const r = document.querySelector('#email').getBoundingClientRect();"
            "return {x:r.x,y:r.y,width:r.width,height:r.height}; })()",
        )
        assert point.scrolled
        assert point.bounds.model_dump() == actual
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    highlight = next(
        record for record in records if record["type"] == "browser.element.highlight"
    )
    assert {key: highlight[key] for key in actual} == actual


def _typing_model(holder, coordinates):
    text = "Grüße + 🙂"
    shortcut = ToolCall("send_keys", {"key": "a", "hold_control": True})
    if coordinates:
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
            lambda request: ToolCall(
                "type_text", {"ref": _ref(request, "Email"), "text": text}
            ),
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
        assert "type_text" in tools
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
                await evaluate(
                    holder["browser"].active_tab,
                    "document.querySelector('#email').value",
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


def _assert_events(streamed, output, stored, coordinates):
    live = [event for event in streamed if isinstance(event, InputEvent)]
    assert live and all(event.browser_id and event.target_id for event in live)
    assert all(event.action_id or isinstance(event, CursorStateEvent) for event in live)
    keys = [event for event in live if event.type == "browser.key.pressed"]
    assert [event.key for event in keys][-7:] == list("Secret!")
    assert keys[-7].modifiers == ("Shift",)
    records = [json.loads(line) for line in output.splitlines()]
    assert any(record["type"] == "browser.cursor.moved" for record in records)
    assert (
        any(record["type"] == "browser.pointer.pressed" for record in records)
        == coordinates
    )
    assert [
        record["key"] for record in records if record["type"] == "browser.key.pressed"
    ] == [event.key for event in keys]
    # Live input events stream to subscribers but stay out of the saved conversation.
    assert '"browser.key.pressed"' not in stored
    assert '"browser.cursor.moved"' not in stored


def _ref(request, name):
    state = latest(request.messages)
    return next(
        element["ref"] for element in state["elements"] if element["name"] == name
    )
