import base64
import json
import re
from io import BytesIO
from unittest.mock import AsyncMock

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
    ChoreographyOverlay,
    Chrome,
    ChromeBrowser,
    DomCapture,
    Input,
    InputPacing,
    NetworkQuiet,
    Readiness,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
    TextObservations,
    Viewport,
    WheelTools,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.core import Bounds, BrowserError, Geometry, Point, Region
from browserrig.kinds import ElementOperation
from browserrig.observation import (  # smelt: ignore[SMT107] -- facade callable
    # Public facade callable; SMT107 confuses it with the same-named module.
    capture,
    render,
)
from browserrig.readiness import BrowserReady
from browserrig.scripts import ELEMENT, ElementArgs
from tests.javascript import evaluate
from tests.observations import has_image, image_id

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "text,pixels,marked",
    [
        pytest.param(False, True, False, id="screenshot"),
        pytest.param(False, True, True, id="screenshot-marks"),
        pytest.param(True, False, False, id="text"),
        pytest.param(True, True, False, id="text-screenshot"),
        pytest.param(True, True, True, id="text-screenshot-marks"),
    ],
)
async def test_perception_delivers_exactly_the_selected_modalities(
    site, monkeypatch, text, pixels, marked
):
    requests = []

    async def respond(request):
        requests.append(request)
        if len(requests) == 1:
            yield ModelChunk(tool_call=ToolCall("list_tabs", {}))
        else:
            yield ModelChunk(text="Done")

    policy = NetworkQuiet(inner=BrowserReady())
    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            Readiness(initial=policy, ongoing=policy) if not (text or marked) else None,
            BrowserPerception(
                capture=ScreenshotCapture() if not (text or marked) else None,
                text=TextObservations(mode="full") if text else None,
                screenshots=Screenshots(
                    trigger=ScreenshotTrigger.EACH_STEP,
                    marks=SetOfMarks() if marked else None,
                    skip_unchanged=False,
                )
                if pixels
                else None,
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(ChoreographyOverlay,),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await evaluate(
            tab,
            """document.body.innerHTML = `<button aria-label="DOM_ONLY_TARGET"
                style="position:absolute;left:100px;top:100px;width:90px;height:32px;
                background:white;border:none">Buy</button>`;""",
        )
        frames = AsyncMock(side_effect=AssertionError("Unexpected DOM extraction"))
        probe = AsyncMock(side_effect=AssertionError("Unexpected DOM readiness probe"))
        if not (text or marked):
            monkeypatch.setattr(tab, "frames", frames)
            monkeypatch.setattr(tab, "main_frame", probe)
        result = await session.run("Inspect the page", max_steps=2)
        snapshot = session.scope[BrowserPerception].snapshot
        assert snapshot is not None and bool(snapshot.elements) is (text or marked)

    assert result.text == "Done" and len(requests) == 2
    images = [
        _check_modalities(request, text=text, pixels=pixels, marked=marked)
        for request in requests
    ]
    if pixels:
        assert images[0] != images[1]
    if not (text or marked):
        frames.assert_not_called()
        probe.assert_not_called()


async def test_vision_on_request_starts_with_an_image_and_refreshes_after_wheel_input(
    site,
):
    frames = []

    async def respond(request):
        (message,) = [message for message in request.messages if has_image(message)]
        frames.append(image_id(message))
        if len(frames) == 1:
            yield ModelChunk(tool_call=ToolCall("scroll", {"delta_y": 800}))
        elif len(frames) == 2:
            yield ModelChunk(tool_call=ToolCall("screenshot", {}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            BrowserPerception(
                capture=ScreenshotCapture(),
                text=None,
                screenshots=Screenshots(skip_unchanged=False),
            ),
            WheelTools(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(ChoreographyOverlay, InputPacing),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await evaluate(tab, "document.body.style.minHeight = '2400px'")
        result = await session.run("Scroll and request a fresh view", max_steps=3)
        position = int(await evaluate(tab, "window.scrollY"))

    assert result.text == "Done" and position > 0
    assert len(frames) == 3
    assert frames[0] == frames[1] != frames[2]


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


async def test_controls_only_capture_keeps_labels_and_dialogs(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <nav aria-label=Primary><a href='/plans'>Plans</a></nav>
            <main><h2>Pricing</h2><p>Every plan renews monthly.</p>
            <label>Seats<input type=number></label><button>Buy</button></main>
            <div role=dialog aria-label=Plan><button>Close</button></div>`;
        """,
        )
        report = await wait_for_page(tab)
        controls = DomCapture(page_prose="off", headings=False, landmarks=False)
        text = render(await capture(tab, controls, report))
        for expected in ('link "Plans"', '"Seats"', 'button "Buy"'):
            assert expected in text
        assert "[DIALOG: Plan]" in text
        for omitted in ("[NAVIGATION", "[MAIN]", "Pricing", "renews monthly"):
            assert omitted not in text
        full = render(await capture(tab, DomCapture(), report))
        for expected in ("[NAVIGATION: Primary]", "[MAIN]", "## Pricing", "renews"):
            assert expected in full


async def test_element_names_come_from_chrome_accessibility_tree(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <button><svg width=16 height=16><title>Close</title></svg></button>
            <input placeholder='Search the web'>
            <a href='/price'><span style='position:absolute;clip:rect(0 0 0 0)'>7,99 â‚¬</span>
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
        "7,99 â‚¬ per piece",
        "Home",
        "Small",
        "Prime",
    } <= names
    assert "Duplicate" not in names
    assert re.search(r"\] div x=\d+ y=\d+ 50x40$", render(state), flags=re.M)


async def test_raw_capture_keeps_refs_and_hidpi_geometry_without_page_mutation(site):
    async with ChromeBrowser(Launch(url=site, viewport=Viewport(scale=2))) as browser:
        devices = Input(browser.input_targets.focused)
        tab = browser.active_tab
        report = await wait_for_page(tab)
        before = await evaluate(tab, "document.documentElement.outerHTML")
        await devices.mouse.move_to(Point(x=700, y=200))
        state = await capture(
            tab,
            DomCapture(),
            report,
            cursor=devices.mouse.position,
            screenshots=True,
        )
        assert await evaluate(tab, "document.documentElement.outerHTML") == before
        assert state.image is not None
        with Image.open(BytesIO(base64.b64decode(state.image))) as image:
            assert image.size == (state.width, state.height)
        refs = [element.ref for element in state.elements]
        assert len(set(refs)) == len(refs)
        rendered = render(state)
        assert all(f"[{element.ref}]" in rendered for element in state.elements)
        assert "never-echo-this" not in rendered
        fresh = await capture(
            tab,
            DomCapture(),
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
                screenshots=Screenshots(
                    trigger=ScreenshotTrigger.EACH_STEP,
                    cursor=show_cursor,
                    marks=SetOfMarks(),
                ),
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
            DomCapture(max_elements=1, max_text_chars=2),
            report,
        )
        assert len(limited.elements) == 1 and len(limited.text) <= 2
        assert any("truncated" in limitation for limitation in limited.limitations)


async def test_default_text_preserves_dense_page_guidance_with_an_explicit_opt_out(
    site,
):
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
        assert "text: Your request was blocked." in render(sparse)
        assert "page text:" not in render(sparse)
        await evaluate(
            tab,
            "document.body.insertAdjacentHTML('beforeend', '<button>Go</button>'.repeat(5))",
        )
        busy = await capture(tab, DomCapture(), report, previous=sparse)
        assert "Your request was blocked." in busy.text
        assert busy.fingerprint != sparse.fingerprint
        controls_only = await capture(tab, DomCapture(page_prose="off"), report)
        assert controls_only.text == ""


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
        devices = Input(browser.input_targets.focused)
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_CANVASES)}")
        await evaluate(
            tab, "document.querySelector('#board').addEventListener('click', () => {})"
        )
        report = await wait_for_page(tab)
        await devices.mouse.move_to(Point(x=150, y=180))
        state = await capture(
            tab,
            DomCapture(),
            report,
            region=Region(x=100, y=150, width=400, height=200),
            zoom=2,
            cursor=devices.mouse.position,
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


async def test_agent_clicks_canvas_through_region_screenshot(site):
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
            yield ModelChunk(tool_call=ToolCall("screenshot", {"region": region}))
        elif step == 1:
            captions.extend(
                line
                for text in texts
                for line in text.splitlines()
                if line.startswith("Screenshot ")
            )
            # Crop pixel (50, 30) is viewport (150, 180), canvas offset (50, 30).
            yield ModelChunk(tool_call=ToolCall("click_at", {"x": 50, "y": 30}))
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
        "scale": 1,
    }


def _check_modalities(request, *, text: bool, pixels: bool, marked: bool) -> str:
    assert (
        any("DOM_ONLY_TARGET" in message.text for message in request.messages) is text
    )
    image_messages = [message for message in request.messages if has_image(message)]
    assert len(image_messages) == int(pixels)
    if not pixels:
        return ""
    (message,) = image_messages
    (part,) = [part for part in message.content if isinstance(part, ImagePart)]
    encoded = part.url.split(",", 1)[1]
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        rgb = image.convert("RGB")
        assert (rgb.getpixel((102, 100)) == (34, 197, 94)) is marked
    return image_id(message)
