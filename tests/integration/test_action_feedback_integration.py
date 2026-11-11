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
    Input,
    InputPacing,
    InputVisualization,
    wait_for_page,
)
from browserrig.core import BrowserError
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("obstruction", ["overlay", "pointer_events"])
async def test_blocked_click_reports_measured_layout_facts(site, obstruction):
    holder = {}
    step = 0

    async def respond(_request):
        nonlocal step
        if step == 0:
            target = next(
                (
                    element
                    for element in holder["perception"].snapshot.elements
                    if element.name == "Target"
                ),
                None,
            )
            assert target is not None
            script = (
                (
                    "document.body.insertAdjacentHTML('beforeend', '<div style=\"position:"
                    "fixed;inset:0;background:white;z-index:99\">Cover</div>')"
                )
                if obstruction == "overlay"
                else "target.style.pointerEvents='none'"
            )
            await evaluate(holder["tab"], script)
            yield ModelChunk(tool_call=ToolCall("click", {"ref": target.ref}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = _agent(site, respond)
    async with agent.session() as session:
        tab = holder["tab"] = session.scope[Browser].active_tab
        holder["perception"] = session.scope[BrowserPerception]
        await wait_for_page(tab)
        await evaluate(
            tab,
            (
                "document.body.innerHTML='<button id=target style=\"position:absolute;"
                "left:100px;top:100px\">Target</button>';window.clicked=0;target.oncli"
                "ck=()=>window.clicked++"
            ),
        )
        result = await session.run("Click Target")
        assert await evaluate(tab, "window.clicked") == 0
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert reply.is_error
    assert "not dispatched" not in reply.text
    assert "ELEMENT_BLOCKED" in reply.text and "bounds=" in reply.text
    assert (
        "reaches <div>" if obstruction == "overlay" else "pointer-events=none"
    ) in reply.text


async def test_click_failure_after_native_input_keeps_uncertainty(site, monkeypatch):
    holder = {}
    step = 0

    async def respond(_request):
        nonlocal step
        if step == 0:
            target = next(
                (
                    element
                    for element in holder["perception"].snapshot.elements
                    if element.name == "Target"
                ),
                None,
            )
            assert target is not None
            yield ModelChunk(tool_call=ToolCall("click", {"ref": target.ref}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = _agent(site, respond)
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        holder["perception"] = session.scope[BrowserPerception]
        await wait_for_page(tab)
        await evaluate(
            tab,
            (
                "document.body.innerHTML='<button id=target>Target</button>';window.c"
                "licked=0;target.onclick=()=>window.clicked++"
            ),
        )
        click = session.scope[Input].mouse.click

        async def click_then_fail(*args, **kwargs):
            await click(*args, **kwargs)
            raise BrowserError("Follow-up failed after native click")

        monkeypatch.setattr(session.scope[Input].mouse, "click", click_then_fail)
        result = await session.run("Click Target")
        assert await evaluate(tab, "window.clicked") == 1
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert reply.is_error and "may have run" in reply.text
    assert "not dispatched" not in reply.text


def _agent(site, respond):
    return Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
        without=(InputPacing, InputVisualization),
    )


@pytest.mark.parametrize("framed", [False, True])
async def test_fixed_body_remains_clickable_when_root_layout_height_is_zero(
    site, framed
):
    holder = {}
    step = 0

    async def respond(_request):
        nonlocal step
        if step == 0:
            target = next(
                (
                    element
                    for element in holder["perception"].snapshot.elements
                    if element.name == "Target"
                ),
                None,
            )
            assert target is not None
            yield ModelChunk(tool_call=ToolCall("click", {"ref": target.ref}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = _agent(site, respond)
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        holder["perception"] = session.scope[BrowserPerception]
        await wait_for_page(tab)
        html = (
            "<style>html{height:0;overflow:auto}body{position:fixed;inset:0;margin:0;overflow:hidden}"
            "#target{position:absolute;left:100px;top:100px}</style>"
            '<button id=target onclick="this.dataset.clicked=1">Target</button>'
        )
        if framed:
            await evaluate(
                tab,
                (
                    "document.body.innerHTML='<iframe "
                    'style="width:500px;height:300px"></iframe>\';'
                ),
            )
            await evaluate(
                tab, f"document.querySelector('iframe').srcdoc={json.dumps(html)}"
            )
            await wait_for_page(tab)
        else:
            await evaluate(
                tab, f"document.documentElement.innerHTML={json.dumps(html)}"
            )
        result = await session.run("Click Target")
        prefix = (
            "document.querySelector('iframe').contentDocument" if framed else "document"
        )
        assert (
            await evaluate(
                tab, prefix + ".documentElement.getBoundingClientRect().height"
            )
            == 0
        )
        assert (
            await evaluate(tab, prefix + ".querySelector('#target').dataset.clicked")
            == "1"
        )
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert not reply.is_error
