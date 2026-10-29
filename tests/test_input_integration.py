import asyncio
import io
import json

import pytest
import yaml
from harnessed import Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
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
from browserrig.events import InputEvent

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("canvas", [False, True])
async def test_typing_shortcuts_password_masking_stream_and_storage(site, tmp_path, canvas):
    holder = {}
    output = io.StringIO()
    step = 0
    text = "Grüße + 🙂"

    class Access(Plugin):
        async def setup(self, browser: Inject[Browser]):
            holder["browser"] = browser

    async def respond(request):
        nonlocal step
        if step == 0:
            if canvas:
                yield ModelChunk(tool_call=ToolCall("click_at", {"x": 80, "y": 18}))
            else:
                yield ModelChunk(
                    tool_call=ToolCall(
                        "type_text", {"ref": _ref(request, "Email"), "text": "old value"}
                    )
                )
        elif step == 1:
            arguments = {"text": text, "clear": True}
            if not canvas:
                arguments["ref"] = _ref(request, "Email")
            yield ModelChunk(tool_call=ToolCall("type_text", arguments))
        elif step == 2:
            assert (
                await holder["browser"].active_tab.evaluate(
                    "document.querySelector('#email').value"
                )
                == text
            )
            yield ModelChunk(tool_call=ToolCall("press_key", {"key": "Control+a"}))
        elif step == 3:
            yield ModelChunk(tool_call=ToolCall("press_key", {"key": "+"}))
        elif step == 4:
            if canvas:
                yield ModelChunk(tool_call=ToolCall("click_at", {"x": 320, "y": 18}))
            else:
                yield ModelChunk(
                    tool_call=ToolCall(
                        "type_text", {"ref": _ref(request, "Password"), "text": "Secret!"}
                    )
                )
        elif step == 5 and canvas:
            yield ModelChunk(tool_call=ToolCall("type_text", {"text": "Secret!", "clear": True}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    directory = tmp_path / "sessions"
    agent = BrowserAgent(
        model=CallbackModel(respond),
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


async def _consume(session, streamed, ready):
    ready.set()
    async for event in session.subscribe(transient=True):
        streamed.append(event)


def _assert_events(streamed, output, directory, canvas):
    live = [event for event in streamed if isinstance(event, InputEvent)]
    assert live and all(event.action_id and event.browser_id and event.target_id for event in live)
    keys = [event for event in live if event.type == "browser.key.pressed"]
    assert [event.key for event in keys if not event.sensitive][-1] == "+"
    private = [event for event in keys if event.sensitive]
    assert private and all(event.key == "" and not event.modifiers for event in private)
    records = [json.loads(line) for line in output.splitlines()]
    assert any(record["type"] == "browser.cursor.moved" for record in records)
    assert any(record["type"] == "browser.pointer.pressed" for record in records) == canvas
    assert "Secret!" not in output
    files = list(directory.rglob("*.jsonl"))
    assert files
    for path in files:
        stored = path.read_text(encoding="utf-8")
        assert '"browser.key.pressed"' not in stored
        assert '"browser.cursor.moved"' not in stored


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

    class Access(Plugin):
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
