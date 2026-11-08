import base64
import json
import re
from io import BytesIO

import pytest
from harnessed import Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.kernel import needs
from harnessed.models import ImagePart, ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel
from PIL import Image

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Chrome,
    ChromeBrowser,
    DomCapture,
    Screenshots,
    ScreenshotTrigger,
    Viewport,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.core import Bounds, BrowserError, Geometry, Point, Region
from browserrig.kinds import ElementOperation
from browserrig.observation import capture, render
from browserrig.scripts import ELEMENT, ElementArgs
from tests.javascript import evaluate
from tests.observations import has_image

pytestmark = pytest.mark.integration


async def test_composed_dom_semantics_click_listeners_and_visible_text(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
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
        state = await capture(tab, DomCapture(max_text_chars=12000), report)
        names = [element.name for element in state.elements]
        for expected in (
            "Wrapped",
            "Check",
            "Listener only",
            "Switch",
            "Editor",
            "Closed shadow",
        ):
            assert names.count(expected) == 1
        assert not {
            "Transparent ancestor",
            "Inert ancestor",
            "Clipped",
        } & set(names)
        covered = next(
            element for element in state.elements if element.name == "Covered"
        )
        assert covered.covered and not covered.in_viewport
        assert "Offscreen" not in names and state.offscreen
        assert next(
            element for element in state.elements if element.name == "Wrapped"
        ).in_viewport
        assert "Slotted label" in state.text and "Closed shadow" in state.text
        assert "Offscreen text" not in state.text
        assert not state.limitations
        checked = next(element for element in state.elements if element.name == "Check")
        assert checked.checked is True
        assert next(
            e for e in state.elements if e.name == "Disabled by fieldset"
        ).disabled


async def test_element_names_come_from_chrome_accessibility_tree(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <button><svg width=16 height=16><title>Close</title></svg></button>
            <input placeholder='Search the web'>
            <a href='/price'><span style='position:absolute;clip:rect(0 0 0 0)'>7,99 €</span>
                <span aria-hidden=true>7<sup>99</sup></span> per piece</a>
            <a href='/home' style='text-transform:uppercase'>Home</a>
            <label><input type=radio name=size>Small</label>
            <label><input type=checkbox style='opacity:0;position:absolute'
                aria-labelledby=prime><i></i></label><span id=prime>Prime</span>
            <a href='/duplicate' aria-hidden=true tabindex=-1><img alt='Duplicate'
                width=20 height=20></a>
            <div tabindex=0 style='width:50px;height:40px'></div>`;
        """,
        )
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
    names = {element.name for element in state.elements}
    assert {
        "Close",
        "Search the web",
        "7,99 € per piece",
        "Home",
        "Small",
        "Prime",
    } <= names
    assert "Duplicate" not in names
    assert re.search(r"\] div x=\d+ y=\d+ 50x40$", render(state), flags=re.M)


@pytest.mark.parametrize("marks", [False, True])
async def test_marks_match_refs_and_hidpi_screenshot_without_page_mutation(site, marks):
    async with ChromeBrowser(Launch(url=site, viewport=Viewport(scale=2))) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        before = await evaluate(tab, "document.documentElement.outerHTML")
        await browser.input.mouse.move_to(Point(x=700, y=200))
        state = await capture(
            tab,
            DomCapture(marks=marks, cursor=True),
            report,
            cursor=browser.input.mouse.position,
            screenshots=True,
        )
        assert await evaluate(tab, "document.documentElement.outerHTML") == before
        assert state.image is not None
        with Image.open(BytesIO(base64.b64decode(state.image))) as image:
            assert image.size == (state.width, state.height)
            assert image.getpixel((700, 200)) == (30, 30, 30)
        refs = [element.ref for element in state.elements]
        assert len(set(refs)) == len(refs)
        rendered = render(state)
        assert all(f"[{element.ref}]" in rendered for element in state.elements)
        assert "never-echo-this" not in rendered
        fresh = await capture(
            tab,
            DomCapture(marks=marks, cursor=True),
            report,
            previous=state,
            screenshots=True,
        )
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


@pytest.mark.parametrize("show_cursor", [False, True])
async def test_model_cursor_marker_is_optional_after_movement_and_click(
    site, show_cursor
):
    step = 0

    async def respond(request):
        nonlocal step
        if step:
            latest_image = next(
                (
                    message
                    for message in reversed(request.messages)
                    if has_image(message)
                ),
                None,
            )
            assert latest_image is not None
            (image_part,) = [
                part for part in latest_image.content if isinstance(part, ImagePart)
            ]
            encoded = image_part.url.split(",", 1)[1]
            with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                expected = (30, 30, 30) if show_cursor else (255, 0, 0)
                assert image.getpixel((60, 80) if step == 1 else (180, 120)) == expected
        if step == 0:
            yield ModelChunk(tool_call=ToolCall("move_mouse", {"x": 60, "y": 80}))
        elif step == 1:
            yield ModelChunk(tool_call=ToolCall("click_at", {"x": 180, "y": 120}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site + "/canvas", viewport=Viewport(scale=2)),
        plugins=[
            BrowserPerception(
                capture=DomCapture(cursor=show_cursor),
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run(
        "Move, click, and inspect the cursor after each action", max_steps=3
    )
    assert result.text == "Done" and step == 3


async def test_limits_are_reported_and_checkbox_state_changes_fingerprint(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        await evaluate(
            tab,
            "document.body.innerHTML = '<label>Toggle<input type=checkbox></label>'",
        )
        before = await capture(tab, DomCapture(), report)
        await evaluate(tab, "document.querySelector('input').checked = true")
        after = await capture(tab, DomCapture(), report)
        assert before.fingerprint != after.fingerprint
        await evaluate(
            tab,
            "document.body.innerHTML = '<button>First</button><button>Second</button>'",
        )
        limited = await capture(
            tab,
            DomCapture(max_elements=1, max_text_chars=2, sparse_text_chars=0),
            report,
        )
        assert len(limited.elements) == 1 and len(limited.text) <= 2
        assert any("truncated" in limitation for limitation in limited.limitations)


async def test_visible_text_is_shown_only_when_the_viewport_holds_few_controls(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<h1>Access denied</h1>
            <p>Your request was blocked.</p><a href='/help'>Help</a>
            <p style='position:absolute;top:3000px'>Below the fold</p>`""",
        )
        sparse = await capture(tab, DomCapture(), report)
        assert (
            "Your request was blocked." in sparse.text
            and "Below the fold" not in sparse.text
        )
        assert "page text:" in render(sparse)
        await evaluate(
            tab,
            "document.body.insertAdjacentHTML('beforeend', '<button>Go</button>'.repeat(5))",
        )
        busy = await capture(tab, DomCapture(), report, previous=sparse)
        assert busy.text == "" and busy.fingerprint != sparse.fingerprint


async def test_challenge_overlay_reads_its_text_but_not_the_page_beneath(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        tiles = "<div tabindex=0 style='width:60px;height:60px'></div>" * 6
        markup = f"""<p>Hidden results</p><a href='/a'>Result</a>
            <div style='position:fixed;inset:0;background:white'>
            <p>Select every square with a duck</p>{tiles}
            <button>\ue900</button><button>Submit</button></div>"""
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        state = await capture(tab, DomCapture(), report)
        assert "Select every square with a duck" in state.text
        assert "Hidden results" not in state.text
        glyph = next(e for e in state.elements if e.in_viewport and e.tag == "button")
        assert glyph.name == ""


async def test_partially_covered_element_uses_exposed_hit_point(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        markup = """<button style='position:absolute;left:20px;top:20px;width:200px;height:80px'>
            Partial</button><div style='position:absolute;left:80px;top:20px;width:140px;
            height:80px;
            background:white'></div>"""
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
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
    async with ChromeBrowser(Launch(url=site, viewport=Viewport(scale=2))) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_CANVASES)}")
        await evaluate(
            tab, "document.querySelector('#board').addEventListener('click', () => {})"
        )
        report = await wait_for_page(tab)
        await browser.input.mouse.move_to(Point(x=150, y=180))
        state = await capture(
            tab,
            DomCapture(cursor=True),
            report,
            region=Region(x=100, y=150, width=400, height=200),
            zoom=2,
            cursor=browser.input.mouse.position,
            screenshots=True,
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
            assert image.getpixel((100, 60)) == (30, 30, 30)
        rendered = render(state)
        assert (
            f"canvas (ref {board.ref}) x=100 y=150 400x200 center=300,250" in rendered
        )
        assert "image: viewport region x=100 y=150 400x200 at 2x zoom" in rendered

        outside = await capture(
            tab,
            DomCapture(),
            report,
            region=Region(x=5000, y=0, width=10, height=10),
            screenshots=True,
        )
        assert outside.geometry is None
        assert any("outside the viewport" in note for note in outside.limitations)
        with Image.open(BytesIO(base64.b64decode(outside.image))) as image:
            assert image.size == (outside.width, outside.height)


async def test_agent_clicks_canvas_through_zoomed_region_screenshot(site):
    holder = {}

    class Access(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _scope):
            browser = self._setup_browser
            holder["browser"] = browser

    step = 0
    captions = []

    async def respond(request):
        nonlocal step
        texts = [message.text for message in request.messages]
        if step == 0:
            assert any("x=100 y=150 400x200 center=300,250" in text for text in texts)
            region = {"x": 100, "y": 150, "width": 400, "height": 200}
            yield ModelChunk(
                tool_call=ToolCall("screenshot", {"region": region, "zoom": 2})
            )
        elif step == 1:
            captions.extend(
                line
                for text in texts
                for line in text.splitlines()
                if line.startswith("Screenshot ")
            )
            # Image pixel (100, 60) at 2x zoom is viewport (150, 180), canvas offset (50, 30).
            yield ModelChunk(tool_call=ToolCall("click_at", {"x": 100, "y": 60}))
        else:
            yield ModelChunk(text="Done")
        step += 1

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW), Access()],
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
        receipts = [
            e for e in result.events if isinstance(e, ToolExecutionFinishedEvent)
        ]
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
