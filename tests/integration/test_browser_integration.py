import asyncio
from urllib.parse import urlsplit

import pytest
from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import (
    Browser,
    Chrome,
    ChromeBrowser,
    Input,
    InputRuntime,
    InputVisualization,
    Runtime,
    Viewport,
    wait_for_page,
)
from browserrig.browser import Connect, Launch
from browserrig.choreography import CursorEnteredEvent, Stage, TabPressedEvent
from browserrig.core import Point
from browserrig.events import BrowserEvent, CursorStateEvent, InputEvent, TabOpenedEvent
from browserrig.input import HumanMotor
from browserrig.kinds import TabGesture
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_custom_setup_reaches_page_and_oopif_sessions(site):
    setup = _SessionProbe()
    viewport = Viewport(width=900, height=700, scale=2)
    options = Launch(
        url=site + "/frame-cross-middle",
        arguments=("--site-per-process",),
        viewport=viewport,
        session_setup=(setup,),
    )
    async with ChromeBrowser(options) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        frames = await tab.frames()
        assert len(frames) == 2
        assert frames[0].cdp.session_id != frames[1].cdp.session_id
        assert setup.sessions == [
            (tab.cdp.session_id, False),
            (frames[1].cdp.session_id, True),
        ]
        assert await tab.viewport_size() == (900, 700)
        assert await evaluate(tab, "devicePixelRatio") == 2


async def test_tabs_land_the_cursor_and_activation_republishes_its_position(site):
    events = []

    async def emit(event):
        events.append(event)

    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            Chrome(),
            InputRuntime(),
            InputVisualization(renderer=None),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        devices = session.scope[Input]
        session.scope.on(BrowserEvent, emit)
        session.scope.on(InputEvent, emit)
        first = browser.active_tab
        # Unwatched, the cursor lands centered and nothing is reported.
        assert not any(isinstance(event, CursorStateEvent) for event in events)
        width, height = await first.viewport_size()
        assert devices.mouse.position == Point(x=width / 2, y=height / 2)
        devices.pace(HumanMotor())
        devices.present(Stage())
        await devices.mouse.move_to(Point(x=100, y=120))
        second = await browser.tabs.open(site)
        assert (
            len(
                [
                    event
                    for event in events
                    if isinstance(event, TabOpenedEvent)
                    and event.target_id == second.id
                ]
            )
            == 1
        )
        assert devices.mouse.position_in(second.id) is not None
        opened = next(event for event in events if isinstance(event, TabPressedEvent))
        assert opened.gesture is TabGesture.OPEN and opened.target_id == first.id
        assert opened.from_position == (100, 120)
        await browser.tabs.activate(first.id)
        pressed = [event for event in events if isinstance(event, TabPressedEvent)][-1]
        assert pressed.gesture is TabGesture.ACTIVATE and pressed.tab_id == first.id
        assert pressed.target_id == second.id
        entered = [event for event in events if isinstance(event, CursorEnteredEvent)][
            -1
        ]
        assert entered.target_id == first.id and entered.to_position == (100, 120)
        last = next(
            event for event in reversed(events) if isinstance(event, CursorStateEvent)
        )
        assert last.target_id == first.id and (last.x, last.y) == (100, 120)


@pytest.mark.parametrize("discovery", [False, True])
async def test_launch_stable_tabs_and_isolated_connect(discovery):
    async with ChromeBrowser() as browser:
        first = browser.active_tab
        assert await evaluate(first, "1 + 1") == 2
        endpoint = browser.client.transport.url
        if discovery:
            endpoint = f"http://{urlsplit(endpoint).netloc}/"
        async with ChromeBrowser(Connect(endpoint=endpoint)) as connected:
            assert connected.active_tab.id != first.id
            connected_target = connected.active_tab.id
        assert browser.client.is_connected
        assert await evaluate(first, "2 + 2") == 4
        second = await browser.tabs.open()
        assert first.cdp.session_id != second.cdp.session_id
        assert first.id != second.id
        assert await evaluate(first, "location.href") == "about:blank"
        assert await browser.tabs.activate(first.id) is first
        assert connected_target not in {tab.id for tab in await browser.tabs.list()}
    assert not browser.client.is_connected
    assert first.closed and second.closed


class _SessionProbe:
    def __init__(self):
        self.sessions = []

    async def apply(self, cdp, *, frame):
        await cdp.page.get_frame_tree()
        self.sessions.append((cdp.session_id, frame))


async def test_viewport_resizes_are_counted_and_report_the_new_size(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        before = tab.viewport_revision
        # Stands in for a person resizing the window; both resize the main frame.
        await tab.cdp.emulation.set_device_metrics_override(
            width=700, height=500, device_scale_factor=1, mobile=False
        )
        async with asyncio.timeout(5):
            while tab.viewport_revision == before:
                await asyncio.sleep(0.02)
        width, height = await tab.viewport_size()
        # The client width excludes a page scrollbar.
        assert width <= 700 and height == 500
