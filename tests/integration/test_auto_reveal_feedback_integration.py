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


@pytest.mark.parametrize("mode", ["editor", "overlay_after_scroll", "locked"])
async def test_reveal_targets_container_and_reports_only_measured_movement(site, mode):
    holder = {}
    called = False
    target_ref = ""

    async def respond(_request):
        nonlocal called, target_ref
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        target = next(
            (
                item
                for item in holder["observe"].snapshot.elements
                if item.name == "Target"
            ),
            None,
        )
        assert target is not None
        target_ref = target.ref
        yield ModelChunk(
            tool_call=ToolCall("type_text", {"ref": target.ref, "text": "Hello"})
        )

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
        without=(InputPacing, InputVisualization),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        holder["observe"] = session.scope[BrowserPerception]
        await wait_for_page(tab)
        html = (
            "<style>body{margin:0;height:2400px}#editor{position:absolute;top:0;"
            "left:0;width:100%;height:800px}#target{position:absolute;top:1200px;"
            "left:100px}</style><div id=editor>Virtual editor</div>"
            '<input id=target aria-label="Target">'
        )
        await evaluate(
            tab,
            f"document.body.innerHTML={json.dumps(html)};"
            "window.wheels=0;editor.addEventListener('wheel',e=>{"
            "window.wheels++;e.preventDefault()},{passive:false})",
        )
        if mode == "overlay_after_scroll":
            await evaluate(
                tab,
                "window.addEventListener('scroll',()=>{document.body.insertAdjacentHTML("
                "'beforeend','<div style=\"position:fixed;inset:0;z-index:99\">Cover</div>')}"
                ",{once:true})",
            )
        elif mode == "locked":
            await evaluate(tab, "document.documentElement.style.overflow='hidden'")
        result = await session.run("Type Hello into Target", max_steps=2)
        actual = await evaluate(
            tab, "({y:scrollY,value:target.value,wheels:window.wheels})"
        )
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert actual["wheels"] == 0
    if mode == "locked":
        assert actual["y"] == 0 and actual["value"] == ""
        assert reply.is_error and "ELEMENT_BLOCKED" in reply.text
        assert "Auto-scrolled" not in reply.text
    else:
        assert actual["y"] > 0
        assert (
            f"Auto-scrolled page to reveal [{target_ref}] (y: 0 → {actual['y']:g})."
            in reply.text
        )
        assert "in frame" not in reply.text and "(CSS px)" not in reply.text
        if mode == "editor":
            assert not reply.is_error and actual["value"] == "Hello"
        else:
            assert reply.is_error and actual["value"] == ""
            assert "ELEMENT_BLOCKED" in reply.text
