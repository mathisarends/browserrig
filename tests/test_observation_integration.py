import base64
import json
from io import BytesIO

import pytest
from harnessed import Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel
from PIL import Image

from browserrig import (
    Browser,
    BrowserAgent,
    ChromeBrowser,
    DomMode,
    LaunchBrowser,
    Viewport,
    wait_for_page,
)
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, Geometry, Region
from browserrig.kinds import ElementOperation
from browserrig.observation import capture
from browserrig.observation.render import render
from browserrig.scripts import ELEMENT
from browserrig.scripts.models import ElementArgs
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_composed_dom_semantics_click_listeners_and_visible_text(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <div onclick=''><button>Wrapped</button></div>
            <label>Check<input type=checkbox checked></label>
            <fieldset disabled><input aria-label='Disabled by fieldset'></fieldset>
            <div id=listener>Listener only</div>
            <div role=switch aria-checked=true>Switch</div>
            <div contenteditable=plaintext-only aria-label=Editor>Editable</div>
            <div id=closed></div><div id=open><span slot=label>Slotted label</span></div>
            <div style='opacity:0'><button>Transparent ancestor</button></div>
            <div inert><button>Inert ancestor</button></div>
            <div style='position:absolute;top:2000px'>Offscreen text<button>Offscreen</button></div>
            <div style='overflow:hidden;width:1px;height:1px'>
                <button style='margin-left:100px'>Clipped</button></div>
            <div style='position:absolute;left:800px;top:100px'>
                <button>Covered</button>
                <div style='position:absolute;inset:0;background:white'></div>
            </div>`;
            document.querySelector('#listener').addEventListener('click', () => {});
            document.querySelector('#closed').attachShadow({mode:'closed'}).innerHTML =
                '<button>Closed shadow</button>';
            document.querySelector('#open').attachShadow({mode:'open'}).innerHTML =
                '<button><slot name=label></slot></button>';
        """,
        )
        report = await wait_for_page(tab)
        state = await capture(tab, DomMode(max_text_chars=12000), report)
        names = [element.name for element in state.elements]
        for expected in ("Wrapped", "Check", "Listener only", "Switch", "Editor", "Closed shadow"):
            assert names.count(expected) == 1
        assert not {
            "Transparent ancestor",
            "Inert ancestor",
            "Clipped",
        } & set(names)
        covered = next(element for element in state.elements if element.name == "Covered")
        assert covered.covered and not covered.in_viewport
        assert not next(
            element for element in state.elements if element.name == "Offscreen"
        ).in_viewport
        assert next(element for element in state.elements if element.name == "Wrapped").in_viewport
        assert "Slotted label" in state.text and "Closed shadow" in state.text
        assert "Offscreen text" not in state.text
        assert not state.limitations
        checked = next(element for element in state.elements if element.name == "Check")
        assert checked.checked is True
        assert next(e for e in state.elements if e.name == "Disabled by fieldset").disabled


@pytest.mark.parametrize("marks", [False, True])
async def test_marks_match_refs_and_hidpi_screenshot_without_page_mutation(site, marks):
    async with ChromeBrowser(LaunchBrowser(url=site, viewport=Viewport(scale=2))) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        before = await evaluate(tab, "document.documentElement.outerHTML")
        state = await capture(tab, DomMode(screenshots=True, marks=marks), report)
        assert await evaluate(tab, "document.documentElement.outerHTML") == before
        assert state.image is not None
        with Image.open(BytesIO(base64.b64decode(state.image))) as image:
            assert image.size == (state.width, state.height)
        refs = [element.ref for element in state.elements]
        assert len(set(refs)) == len(refs)
        rendered = render(state)
        assert all(f"[{element.ref}]" in rendered for element in state.elements)
        assert "never-echo-this" not in rendered
        fresh = await capture(tab, DomMode(screenshots=True, marks=marks), report, previous=state)
        assert fresh.fingerprint == state.fingerprint
        assert [element.ref for element in fresh.elements] == refs
        assert not any(element.new for element in fresh.elements)
        first = state.elements[0]
        await evaluate(tab, "document.body.replaceChildren()")
        with pytest.raises(BrowserError, match="STALE_ELEMENT"):
            await (await tab.main_frame()).run_on_node(
                first.backend_id,
                ELEMENT,
                ElementArgs(operation=ElementOperation.POINT, value=False),
                user_gesture=True,
            )


async def test_limits_are_reported_and_checkbox_state_changes_fingerprint(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        await evaluate(
            tab, "document.body.innerHTML = '<label>Toggle<input type=checkbox></label>'"
        )
        before = await capture(tab, DomMode(screenshots=False), report)
        await evaluate(tab, "document.querySelector('input').checked = true")
        after = await capture(tab, DomMode(screenshots=False), report)
        assert before.fingerprint != after.fingerprint
        await evaluate(
            tab, "document.body.innerHTML = '<button>First</button><button>Second</button>'"
        )
        limited = await capture(tab, DomMode(max_elements=1, max_text_chars=2), report)
        assert len(limited.elements) == 1 and len(limited.text) <= 2
        assert any("truncated" in limitation for limitation in limited.limitations)


async def test_partially_covered_element_uses_exposed_hit_point(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        markup = """<button style='position:absolute;left:20px;top:20px;width:200px;height:80px'>
            Partial</button><div style='position:absolute;left:80px;top:20px;width:140px;
            height:80px;
            background:white'></div>"""
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomMode(screenshots=False), report)
        element = next(e for e in state.elements if e.name == "Partial")
        point = await (await tab.main_frame()).run_on_node(
            element.backend_id,
            ELEMENT,
            ElementArgs(operation=ElementOperation.POINT, value=False),
            user_gesture=True,
        )
        assert 20 <= point["x"] < 80


_CANVASES = """<style>body{margin:0}</style>
    <canvas id=board width=400 height=200
        style='position:absolute;left:100px;top:150px;width:400px;height:200px'></canvas>
    <canvas aria-label=Icon width=10 height=10
        style='position:absolute;left:0;top:0;width:10px;height:10px'></canvas>
    <div style='position:absolute;left:600px;top:100px'>
        <canvas width=100 height=100></canvas>
        <div style='position:absolute;inset:0;background:white'></div>
    </div>"""


async def test_dom_lists_visible_canvases_and_crops_zoomed_region_screenshots(site):
    async with ChromeBrowser(LaunchBrowser(url=site, viewport=Viewport(scale=2))) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_CANVASES)}")
        await evaluate(tab, "document.querySelector('#board').addEventListener('click', () => {})")
        report = await wait_for_page(tab)
        state = await capture(
            tab,
            DomMode(screenshots=True),
            report,
            region=Region(x=100, y=150, width=400, height=200),
            zoom=2,
        )
        assert [canvas.bounds for canvas in state.canvases] == [
            Bounds(x=100, y=150, width=400, height=200)
        ]
        board = next(element for element in state.elements if element.tag == "canvas")
        assert state.canvases[0].ref == board.ref
        assert state.geometry == Geometry(x=100, y=150, width=400, height=200, scale=2)
        assert state.image is not None
        with Image.open(BytesIO(base64.b64decode(state.image))) as image:
            assert image.size == (800, 400)
        rendered = render(state)
        assert f"canvas (ref {board.ref}) x=100 y=150 400x200 center=300,250" in rendered
        assert "image: viewport region x=100 y=150 400x200 at 2x zoom" in rendered

        outside = await capture(
            tab, DomMode(screenshots=True), report, region=Region(x=5000, y=0, width=10, height=10)
        )
        assert outside.geometry is None
        assert any("outside the viewport" in note for note in outside.limitations)
        with Image.open(BytesIO(base64.b64decode(outside.image))) as image:
            assert image.size == (outside.width, outside.height)


async def test_agent_clicks_canvas_through_zoomed_region_screenshot(site):
    holder = {}

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, browser: Inject[Browser]):
            holder["browser"] = browser

    step = 0
    captions = []

    async def respond(request):
        nonlocal step
        texts = [message.text for message in request.messages]
        if step == 0:
            assert any("x=100 y=150 400x200 center=300,250" in text for text in texts)
            region = {"x": 100, "y": 150, "width": 400, "height": 200}
            yield ModelChunk(tool_call=ToolCall("screenshot", {"region": region, "zoom": 2}))
        elif step == 1:
            captions.extend(text for text in texts if text.startswith("Screenshot "))
            # Image pixel (100, 60) at 2x zoom is viewport (150, 180), canvas offset (50, 30).
            yield ModelChunk(tool_call=ToolCall("click_at", {"x": 100, "y": 60}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        mode=DomMode(),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Access()],
    )
    async with agent.session() as session:
        tab = holder["browser"].active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_CANVASES)}")
        await evaluate(
            tab,
            """const board = document.querySelector('#board');
            board.addEventListener('click', (e) => {
                board.dataset.offset = `${e.offsetX},${e.offsetY}`;
            });""",
        )
        result = await session.run("Click the board", max_steps=5)
        assert result.text == "Done"
        receipts = [e for e in session.events if isinstance(e, ToolExecutionFinishedEvent)]
        assert receipts and not any(receipt.result.is_error for receipt in receipts)
        offset = await evaluate(tab, "document.querySelector('#board').dataset.offset")
        assert offset == "50,30"
    assert captions
    assert json.loads(captions[-1].split("; geometry=")[1]) == {
        "x": 100,
        "y": 150,
        "width": 400,
        "height": 200,
        "scale": 2,
    }
