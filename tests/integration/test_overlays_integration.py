import asyncio
import base64
import shutil
import subprocess
from io import BytesIO

import pytest
from harnessed import Agent
from harnessed.testing import ScriptedModel
from PIL import Image

from browserrig import (
    Activity,
    Browser,
    Chrome,
    ChromeBrowser,
    DomCapture,
    IframeRenderer,
    InputVisualization,
    Point,
    VideoRecording,
    wait_for_page,
)
from browserrig.browser import Launch, screenshot
from browserrig.choreography import FindBarEvent, FindResultsEvent
from browserrig.core import ReadinessStatus
from browserrig.events import KeyPressedEvent
from browserrig.observation import capture, find_text
from browserrig.observation.content import extract_content
from browserrig.scripts import Script, ScriptArgs
from tests.javascript import evaluate

pytestmark = pytest.mark.integration

_TICKER = Script(
    "ticker",
    """function browserrigTicker() {
        setInterval(() => document.querySelector('#ticker').textContent = 'OVERLAY_ONLY', 20);
    }""",
    ScriptArgs,
    lambda _: None,
)


async def test_overlay_is_visible_click_through_and_absent_from_all_page_reads(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """new Promise((resolve) => {
          const iframe = document.createElement('iframe');
              iframe.style.cssText = 'position:fixed;left:20px;top:400px;width:600px;height:180px';
          iframe.src = '/inner'; iframe.onload = () => resolve();
          document.body.append(iframe);
        })""",
        )
        overlay = await tab.overlays.mount(
            html="""<!doctype html><style>body{margin:0;background:transparent}
              #ticker{position:absolute;left:0;top:0;width:200px;height:100px;background:red}
              </style><button id=ticker>OVERLAY_ONLY</button>""",
            script=_TICKER,
        )
        report = await wait_for_page(tab)
        assert report.status == ReadinessStatus.READY
        snapshot = await capture(tab, DomCapture(), report)
        assert "OVERLAY_ONLY" not in snapshot.text
        assert all(element.name != "OVERLAY_ONLY" for element in snapshot.elements)
        assert any(element.name == "Inside" for element in snapshot.elements)
        content = await extract_content(tab)
        assert "OVERLAY_ONLY" not in content.markdown
        found = await find_text(tab, ("OVERLAY_ONLY",), session="overlay")
        assert found.total == 0
        visible = _pixel(await screenshot(tab, overlays=True))
        clean = _pixel(await screenshot(tab))
        assert visible == (255, 0, 0) and clean != visible
        submit = next(
            element for element in snapshot.elements if element.name == "Submit"
        )
        point = submit.bounds
        await browser.input.mouse.click(
            Point(x=point.x + point.width / 2, y=point.y + point.height / 2)
        )
        assert (
            await evaluate(tab, "document.querySelector('#submit').textContent")
            == "Done"
        )
        await overlay.close()
        await overlay.close()
        assert _pixel(await screenshot(tab, overlays=True)) == clean


async def test_overlay_restores_on_navigation_and_stays_closed(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        overlay = await tab.overlays.mount(html="<b>OVERLAY_ONLY</b>")
        await tab.navigate(site + "/other")
        await wait_for_page(tab)
        await overlay.send({"type": "refresh"})
        assert len((await tab.frame_tree()).child_frames or ()) == 1
        assert len(await tab.frames()) == 1
        await evaluate(tab, "document.querySelector('iframe').remove()")
        await overlay.send({"type": "refresh"})
        assert len((await tab.frame_tree()).child_frames or ()) == 1
        await overlay.close()
        await overlay.send({"type": "refresh"})
        assert not (await tab.frame_tree()).child_frames


async def test_overlay_capture_cancellation_restores_visibility(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await tab.overlays.mount(html="<style>body{margin:0;background:red}</style>")
        with pytest.raises(asyncio.CancelledError):
            async with tab.overlays.hidden():
                raise asyncio.CancelledError()
        assert _pixel(await screenshot(tab, overlays=True)) == (255, 0, 0)


async def test_input_visualization_renders_native_events_and_restores_after_navigation(
    site,
):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[Chrome.launch(url=site), InputVisualization()],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        await wait_for_page(tab)
        await browser.input.mouse.move_to(Point(x=300, y=200))
        await tab.emit(KeyPressedEvent(key="a", modifiers=("Control",), duration=2))
        state = await evaluate(
            tab,
            """(() => {
          const surface = document.querySelector('iframe').contentDocument;
          return {cursor: surface.querySelector('#cursor').style.transform,
            keys: [...surface.querySelectorAll('.keyboard-key[data-pressed="true"]')]
              .map(key => key.textContent)};
        })()""",
        )
        assert state == {"cursor": "translate(300px, 200px)", "keys": ["A", "Ctrl"]}
        found = await find_text(tab, ("Submit",), session="renderer")
        await tab.emit(FindBarEvent(visible=True))
        await tab.emit(
            FindResultsEvent(
                query="Submit", total=found.total, active=1, marks=found.marks
            )
        )
        assert (
            await evaluate(
                tab,
                "document.querySelector('iframe').contentDocument.querySelectorAll('.match.active').length",
            )
            == 1
        )
        await browser.input.keyboard.type_text("private", sensitive=True)
        shown = await evaluate(
            tab, "document.querySelector('iframe').contentDocument.body.textContent"
        )
        assert "private" not in shown and "•" in shown
        await tab.navigate(site + "/other")
        await wait_for_page(tab)
        await browser.input.mouse.move_to(Point(x=120, y=100))
        assert (
            await evaluate(
                tab,
                "document.querySelector('iframe').contentDocument.querySelector('#cursor').style.transform",
            )
            == "translate(120px, 100px)"
        )
        assert len(await tab.frames()) == 1


async def test_event_only_visualization_has_no_iframe_or_observation_dependency(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[Chrome.launch(url=site), InputVisualization(renderer=None)],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        await browser.input.mouse.move_to(Point(x=100, y=100))
        assert not (await browser.active_tab.frame_tree()).child_frames


@pytest.mark.parametrize("theme", ["dark", "light"])
async def test_renderer_layout_remains_transparent_and_highlights_german_keys(
    site, theme
):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Chrome.launch(url=site),
            InputVisualization(
                renderer=IframeRenderer(
                    name="Research", keyboard_layout="de", theme=theme
                )
            ),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        await wait_for_page(tab)
        await browser.input.mouse.move_to(Point(x=200, y=200))
        await tab.emit(KeyPressedEvent(key="ä", duration=2))
        state = await evaluate(
            tab,
            """(() => {
            const surface = document.querySelector('iframe').contentDocument;
            return {name: surface.querySelector('#cursor-name').textContent,
              theme: surface.documentElement.dataset.theme,
              rows: surface.querySelectorAll('.keyboard-row').length,
              pressed: [...surface.querySelectorAll('[data-pressed="true"]')]
                .map(key=>key.textContent)};
        })()""",
        )
        assert state == {
            "name": "Research",
            "theme": theme,
            "rows": 5,
            "pressed": ["Ä"],
        }
        visible = await screenshot(tab, overlays=True)
        clean = await screenshot(tab)
        assert _pixel(visible, (1200, 300)) == _pixel(clean, (1200, 300))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="Requires FFmpeg")
async def test_video_records_overlay_without_clean_screenshot_gaps(tmp_path, site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            Chrome.launch(url=site),
            VideoRecording(tmp_path, width=640, height=400, frame_rate=15),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        recording = session.scope[VideoRecording]
        await tab.overlays.mount(html="<style>body{margin:0;background:red}</style>")
        await asyncio.sleep(0.25)
        assert _pixel(await screenshot(tab)) != (255, 0, 0)
        await asyncio.sleep(0.25)
    assert len(recording.result.sources) == 2
    decoded = await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(recording.result.path),
            "-vf",
            "scale=1:1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    colors = list(zip(*[iter(decoded.stdout)] * 3, strict=True))
    red = [r > 180 and g < 60 and b < 60 for r, g, b in colors]
    assert any(red)
    assert all(red[red.index(True) :])


async def test_overlay_works_under_restrictive_page_csp(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """(() => {
          const meta = document.createElement('meta');
          meta.httpEquiv = 'Content-Security-Policy';
          meta.content = "default-src 'none'; script-src 'none'; " +
            "style-src 'none'; frame-src 'none'";
          document.head.append(meta);
        })()""",
        )
        await tab.overlays.mount(html="<style>body{margin:0;background:red}</style>")
        assert _pixel(await screenshot(tab, overlays=True)) == (255, 0, 0)


def _pixel(image, position=(150, 75)):
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        return source.convert("RGB").getpixel(position)
