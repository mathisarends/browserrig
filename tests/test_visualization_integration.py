import asyncio

import pytest
from harnessed import Agent, Plugin
from harnessed.testing import ScriptedModel

from browserrig import (
    Browser,
    Chrome,
    IframeRenderer,
    InputVisualization,
    Point,
    Viewport,
)
from browserrig.browser import Frame
from browserrig.choreography import FileTransferEvent
from browserrig.core import FileTransferDirection
from browserrig.events import (
    CursorStateEvent,
    DownloadCompletedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
    KeyPressedEvent,
    ScrollStartedEvent,
)
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


class _UploadReceipts(Plugin):
    """The upload publisher boundary; the renderer does not own its events."""

    events = (FilesUploadedEvent,)


async def test_file_cards_wait_for_explicit_completion_receipts(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[Chrome.launch(url=site), InputVisualization(), _UploadReceipts()],
    )
    async with agent.session() as session:
        tab = session.ctx[Browser].active_tab
        await tab.emit(
            DownloadStartedEvent(download_id="file", filename="report.pdf", url=site)
        )
        await asyncio.sleep(0.65)
        assert (
            await _surface(tab, "document.querySelector('#download').dataset.state")
            == "active"
        )
        await tab.emit(
            DownloadCompletedEvent(download_id="file", filename="report.pdf", size=123)
        )
        assert (
            await _surface(tab, "document.querySelector('#download').dataset.state")
            == "completed"
        )
        await tab.emit(
            FileTransferEvent(
                direction=FileTransferDirection.UPLOAD,
                paths=("report.pdf",),
                duration=0.1,
                x=80,
                y=80,
            )
        )
        await asyncio.sleep(0.25)
        assert (
            await _surface(tab, "document.querySelector('#upload').dataset.state")
            == "active"
        )
        await tab.emit(FilesUploadedEvent(paths=("report.pdf",), ref="upload"))
        assert (
            await _surface(tab, "document.querySelector('#upload').dataset.state")
            == "completed"
        )


async def test_scroll_feedback_is_visible_during_native_wheel_input(site):
    agent = Agent(
        model=ScriptedModel([]), plugins=[Chrome.launch(url=site), InputVisualization()]
    )
    async with agent.session() as session:
        browser = session.ctx[Browser]
        tab = browser.active_tab
        observed = []

        async def started(_event: ScrollStartedEvent):
            observed.append(await evaluate(tab, "scrollY"))
            assert (
                await _surface(
                    tab, "document.querySelector('#cursor').dataset.scrolling"
                )
                == "true"
            )

        session.ctx.on(ScrollStartedEvent, started, priority=10)
        await browser.mouse.scroll(delta_y=500, point=Point(x=500, y=400))
        assert observed == [0]
        assert await evaluate(tab, "scrollY") > 450


async def test_keyboard_fits_a_compact_viewport_and_keeps_secret_keys_private(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Chrome.launch(url=site, viewport=Viewport(width=360, height=640)),
            InputVisualization(renderer=IframeRenderer(keyboard_layout="de")),
        ],
    )
    async with agent.session() as session:
        browser = session.ctx[Browser]
        tab = browser.active_tab
        await browser.mouse.move_to(Point(x=300, y=600))
        await tab.emit(KeyPressedEvent(key="•", duration=2))
        result = await _surface(
            tab,
            """(() => {
            const keyboard = document.querySelector('#keyboard').getBoundingClientRect();
            return {left:keyboard.left,right:keyboard.right,top:keyboard.top,bottom:keyboard.bottom,
              active:document.querySelectorAll('[data-pressed="true"]').length,
              protected:document.querySelector('#keyboard').dataset.protected};
        })()""",
        )
        assert 0 <= result["left"] < result["right"] <= 360
        assert 0 <= result["top"] < result["bottom"] <= 640
        assert result["active"] == 0 and result["protected"] == "true"


async def test_long_cursor_badge_stays_inside_a_compact_viewport(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Chrome.launch(url=site, viewport=Viewport(width=360, height=640)),
            InputVisualization(renderer=IframeRenderer(name="W" * 40)),
        ],
    )
    async with agent.session() as session:
        tab = session.ctx[Browser].active_tab
        for x, y in ((3, 3), (357, 637)):
            await tab.emit(CursorStateEvent(x=x, y=y))
            bounds = await _surface(
                tab,
                """(() => {
                const r=document.querySelector('#cursor-name').getBoundingClientRect();
                return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};
            })()""",
            )
            assert 0 <= bounds["left"] < bounds["right"] <= 360
            assert 0 <= bounds["top"] < bounds["bottom"] <= 640


async def _surface(tab, expression):
    """Read only the owned iframe, in its existing isolated world."""
    tree = await tab.frame_tree()
    frame_id = next(
        frame.frame.id
        for frame in tree.child_frames
        if frame.frame.name.startswith("browserrig-overlay-")
    )
    frame = Frame(frame_id, tab.cdp, worlds=tab.worlds)
    return await evaluate(frame, expression)
