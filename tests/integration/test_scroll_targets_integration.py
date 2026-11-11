import json
from contextlib import asynccontextmanager

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel, call

from browserrig import (
    Agent,
    Browser,
    Chrome,
    Input,
    InputPacing,
    InputVisualization,
    wait_for_page,
)
from browserrig.core import Point
from tests.javascript import evaluate
from tests.observations import latest

pytestmark = pytest.mark.integration

_EDITOR = """<style>
    html{scroll-behavior:smooth}
    body{margin:0;width:2400px;height:2400px}
    #editor{position:absolute;left:0;top:0;width:100vw;height:90vh;overflow:auto}
    #code{height:1800px;width:1800px;background:#def}
    #branch{position:absolute;top:1000px;left:160px}
    </style>
    <div id=editor role=region aria-label="Code editor" tabindex=0>
      <div id=code>Scrollable code</div>
    </div>
    <input id=branch aria-label="Target Branch" value=main>"""


async def test_page_scroll_ignores_editor_under_cursor_and_allows_branch_input(
    site,
):
    step = 0

    async def respond(request):
        nonlocal step
        step += 1
        if step == 1:
            yield ModelChunk(
                tool_call=ToolCall("scroll_page", {"delta_y": 650, "delta_x": 120})
            )
        elif step == 2:
            state = await _positions(tab)
            assert state == {"page_x": 120, "page_y": 650, "editor_x": 0, "editor_y": 0}
            assert session.scope[Input].mouse.position == Point(x=400, y=250)
            assert await evaluate(tab, "window.wheels") == []
            ref = _ref(request, "Target Branch")
            yield ModelChunk(
                tool_call=ToolCall("type_text", {"ref": ref, "text": "update-title"})
            )
        else:
            yield ModelChunk(text="Done")

    async with _editor_session(site, CallbackModel(respond)) as (
        session,
        _browser,
        tab,
    ):
        result = await session.run("Scroll the page and enter the branch", max_steps=3)
        receipts = _receipts(result)
        assert result.text == "Done" and len(receipts) == 2
        assert all(not receipt.is_error for receipt in receipts)
        assert "Page scrolled from x=0, y=0 to x=120, y=650" in receipts[0].text
        assert (
            await evaluate(tab, "document.querySelector('#branch').value")
            == "update-title"
        )


async def test_element_scroll_moves_only_container_and_preserves_cursor(site):
    called = False

    async def respond(request):
        nonlocal called
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        yield ModelChunk(
            tool_call=ToolCall(
                "scroll_element",
                {"ref": _ref(request, "Code editor"), "delta_y": 180, "delta_x": 120},
            )
        )

    async with _editor_session(site, CallbackModel(respond)) as (
        session,
        _browser,
        tab,
    ):
        result = await session.run("Scroll the editor", max_steps=2)
        receipts = _receipts(result)
        assert result.text == "Done" and len(receipts) == 1
        assert not receipts[0].is_error
        state = await _positions(tab)
        assert state["page_x"] == state["page_y"] == 0
        assert state["editor_x"] == 120
        assert state["editor_y"] == pytest.approx(180, abs=1)
        assert "Element scrolled from x=0, y=0 to x=120, y=180" in receipts[0].text
        assert session.scope[Input].mouse.position == Point(x=400, y=250)
        assert await evaluate(tab, "window.wheels") == []


async def test_page_scroll_reports_boundary_and_can_scroll_back_up(site):
    model = ScriptedModel(
        [
            call("scroll_page", delta_y=10000),
            call("scroll_page", delta_y=10000),
            call("scroll_page", delta_y=-10000),
            "Done",
        ]
    )
    async with _editor_session(site, model) as (session, _browser, tab):
        result = await session.run("Scroll to the end and return", max_steps=4)
        receipts = _receipts(result)
        assert len(receipts) == 3 and all(not receipt.is_error for receipt in receipts)
        assert "Page scrolled" in receipts[0].text
        assert "Page did not move" in receipts[1].text
        assert "Page boundary reached" in receipts[1].text
        assert "to x=0, y=0" in receipts[2].text
        assert await _positions(tab) == {
            "page_x": 0,
            "page_y": 0,
            "editor_x": 0,
            "editor_y": 0,
        }
        assert await evaluate(tab, "window.wheels") == []


async def test_element_boundary_never_scrolls_parent_or_page(site):
    step = 0

    async def respond(request):
        nonlocal step
        step += 1
        if step <= 2:
            yield ModelChunk(
                tool_call=ToolCall(
                    "scroll_element",
                    {"ref": _ref(request, "Code editor"), "delta_y": 10000},
                )
            )
        else:
            yield ModelChunk(text="Done")

    async with _editor_session(site, CallbackModel(respond)) as (
        session,
        _browser,
        tab,
    ):
        await evaluate(
            tab,
            """(() => {
            const parent=document.createElement('div');
            parent.id='parent';
            parent.setAttribute('role','region');
            parent.setAttribute('aria-label','Outer panel');
            parent.style='position:absolute;top:0;left:0;width:100vw;height:90vh;overflow:auto';
            const content=document.createElement('div');
            content.style.height='2000px';
            const editor=document.querySelector('#editor');
            editor.style.position='relative';editor.style.height='300px';
            content.appendChild(editor);parent.appendChild(content);
            document.body.appendChild(parent);
        })()""",
        )
        await wait_for_page(tab)
        result = await session.run("Scroll only the editor to its end", max_steps=3)
        receipts = _receipts(result)
        assert len(receipts) == 2 and all(not r.is_error for r in receipts)
        assert "Element scrolled" in receipts[0].text
        assert "Element did not move" in receipts[1].text
        assert "Element boundary reached" in receipts[1].text
        state = await evaluate(
            tab,
            "({page:scrollY,parent:document.querySelector('#parent').scrollTop,"
            "editor:document.querySelector('#editor').scrollTop,"
            "maximum:document.querySelector('#editor').scrollHeight-"
            "document.querySelector('#editor').clientHeight})",
        )
        assert state["page"] == state["parent"] == 0
        assert state["editor"] == state["maximum"] > 0
        assert await evaluate(tab, "window.wheels") == []


async def test_element_scroll_rejects_regular_control_without_scrolling_ancestors(site):
    called = False

    async def respond(request):
        nonlocal called
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        yield ModelChunk(
            tool_call=ToolCall(
                "scroll_element",
                {"ref": _ref(request, "Target Branch"), "delta_y": 400},
            )
        )

    async with _editor_session(site, CallbackModel(respond)) as (
        session,
        _browser,
        tab,
    ):
        result = await session.run("Try to scroll the branch input", max_steps=2)
        receipts = _receipts(result)
        assert len(receipts) == 1 and receipts[0].is_error
        assert "not a scrollable container" in receipts[0].text
        assert await _positions(tab) == {
            "page_x": 0,
            "page_y": 0,
            "editor_x": 0,
            "editor_y": 0,
        }
        assert await evaluate(tab, "document.querySelector('#branch').value") == "main"


@pytest.mark.parametrize("overflow", ["hidden", "clip"])
async def test_page_scroll_respects_page_scroll_locks(site, overflow):
    async with _editor_session(
        site, ScriptedModel([call("scroll_page", delta_y=400), "Done"])
    ) as (session, _browser, tab):
        await evaluate(tab, f"document.documentElement.style.overflow='{overflow}'")
        result = await session.run("Scroll the locked page", max_steps=2)
        receipts = _receipts(result)
        assert len(receipts) == 1 and not receipts[0].is_error
        assert "Page did not move" in receipts[0].text
        assert "Page scrolling is disabled" in receipts[0].text
        assert await _positions(tab) == {
            "page_x": 0,
            "page_y": 0,
            "editor_x": 0,
            "editor_y": 0,
        }


async def test_page_scroll_does_not_scroll_iframe_under_cursor(site):
    async with _editor_session(
        site, ScriptedModel([call("scroll_page", delta_y=400), "Done"])
    ) as (session, _browser, tab):
        await evaluate(
            tab,
            """document.querySelector('#editor').remove();
            const frame=document.createElement('iframe');
            frame.style='position:absolute;left:0;top:0;width:100vw;height:90vh;border:0';
            frame.srcdoc='<style>body{height:3000px}</style>Iframe content';
            document.body.appendChild(frame);""",
        )
        await wait_for_page(tab)
        await session.scope[Input].mouse.move_to(Point(x=400, y=250))
        result = await session.run("Scroll the outer page", max_steps=2)
        receipts = _receipts(result)
        assert len(receipts) == 1 and not receipts[0].is_error
        state = await evaluate(
            tab,
            "({outer:scrollY,inner:document.querySelector('iframe').contentWindow.scrollY})",
        )
        assert state == {"outer": 400, "inner": 0}


async def test_element_scroll_targets_container_in_its_own_iframe(site):
    called = False

    async def respond(request):
        nonlocal called
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        yield ModelChunk(
            tool_call=ToolCall(
                "scroll_element", {"ref": _ref(request, "Code editor"), "delta_y": 200}
            )
        )

    async with _editor_session(site, CallbackModel(respond)) as (
        session,
        _browser,
        tab,
    ):
        await evaluate(
            tab,
            "document.querySelector('#editor').remove();"
            "const frame=document.createElement('iframe');"
            "frame.style='position:absolute;top:0;left:0;width:600px;height:400px';"
            f"frame.srcdoc={json.dumps(_EDITOR)};document.body.appendChild(frame)",
        )
        await wait_for_page(tab)
        result = await session.run("Scroll the iframe's editor", max_steps=2)
        receipts = _receipts(result)
        assert len(receipts) == 1 and not receipts[0].is_error
        state = await evaluate(
            tab,
            "({page:scrollY,"
            "frame:document.querySelector('iframe').contentWindow.scrollY,"
            "editor:document.querySelector('iframe').contentDocument."
            "querySelector('#editor').scrollTop})",
        )
        assert state == {"page": 0, "frame": 0, "editor": 200}


@asynccontextmanager
async def _editor_session(site, model):
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
        without=(InputPacing, InputVisualization),
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML={json.dumps(_EDITOR)}")
        await wait_for_page(tab)
        await session.scope[Input].mouse.move_to(Point(x=400, y=250))
        await evaluate(
            tab,
            "window.wheels=[];document.addEventListener('wheel',e=>window.wheels.push(e.isTrusted))",
        )
        yield session, browser, tab


async def _positions(tab):
    return await evaluate(
        tab,
        "({page_x:scrollX,page_y:scrollY,editor_x:document.querySelector('#editor').scrollLeft,"
        "editor_y:document.querySelector('#editor').scrollTop})",
    )


def _receipts(result):
    return [
        event.result
        for event in result.events
        if isinstance(event, ToolExecutionFinishedEvent)
    ]


def _ref(request, name):
    snapshot = latest(request.messages)
    return next(e["ref"] for e in snapshot["elements"] if e["name"] == name)
