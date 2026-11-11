import json

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Chrome,
    InputPacing,
    InputVisualization,
    wait_for_page,
)
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "initial,clear,expected,deletes",
    [
        ("", True, "patrick", 0),
        ("old", True, "patrick", 1),
        ("prefix-", False, "prefix-patrick", 0),
    ],
)
async def test_typing_preserves_selected_chips_and_replaces_only_nonempty_text(
    site, initial, clear, expected, deletes
):
    agent, holder = _agent(site, clear)
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await wait_for_page(tab)
        await _mount(tab, initial)
        holder["perception"] = session.scope[BrowserPerception]
        result = await session.run("Enter the next member")
        state = await evaluate(
            tab,
            "({value:field.value,focus:document.activeElement.id,keys:window.keys,chip:chip.textContent})",
        )
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert not reply.is_error
    assert state["value"] == expected and state["focus"] == "field"
    assert state["chip"] == "Selected member"
    assert state["keys"].count("Backspace") == deletes


@pytest.mark.parametrize("when", ["clear", "first_character"])
async def test_typing_stops_when_the_addressed_field_loses_focus(site, when):
    agent, holder = _agent(site, True)
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await wait_for_page(tab)
        await _mount(tab, "old" if when == "clear" else "")
        script = (
            "field.addEventListener('keydown',e=>{if(e.key==='Backspace'){e.preventDefault();other.focus()}})"
            if when == "clear"
            else "field.addEventListener('input',()=>other.focus())"
        )
        await evaluate(tab, script)
        holder["perception"] = session.scope[BrowserPerception]
        result = await session.run("Enter the next member")
        state = await evaluate(
            tab,
            "({value:field.value,other:other.value,focus:document.activeElement.id})",
        )
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert reply.is_error and "lost focus" in reply.text
    assert state == {
        "value": "old" if when == "clear" else "p",
        "other": "",
        "focus": "other",
    }


async def _mount(tab, initial):
    html = (
        "<button id=chip>Selected member</button>"
        '<input id=field aria-label="Username"><input id=other aria-label="Other">'
    )
    await evaluate(
        tab,
        f"document.body.innerHTML={json.dumps(html)};field.value={json.dumps(initial)};"
        "field.setSelectionRange(field.value.length,field.value.length);window.keys=[];"
        "field.addEventListener('keydown',e=>{window.keys.push(e.key);if(e.key==='Backspace'&&!field.value){e.preventDefault();chip.focus()}})",
    )


def _agent(site, clear):
    holder = {}
    step = 0

    async def respond(_request):
        nonlocal step
        if step == 0:
            target = next(
                (
                    element
                    for element in holder["perception"].snapshot.elements
                    if element.name == "Username"
                ),
                None,
            )
            assert target is not None
            yield ModelChunk(
                tool_call=ToolCall(
                    "type_text", {"ref": target.ref, "text": "patrick", "clear": clear}
                )
            )
        else:
            yield ModelChunk(text="Done")
        step += 1

    return Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
        without=(InputPacing, InputVisualization),
    ), holder
