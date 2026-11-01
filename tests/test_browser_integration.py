from urllib.parse import urlsplit

import pytest

from browserrig import ChromeBrowser, Connect
from browserrig.core import Point
from browserrig.events import (
    CursorEnteredEvent,
    CursorStateEvent,
    TabOpenedEvent,
    TabPressedEvent,
)
from browserrig.kinds import TabGesture
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_tabs_seed_centered_cursor_and_activation_republishes_existing_position(
    site,
):
    events = []

    async def emit(event):
        events.append(event)

    async with ChromeBrowser(emit=emit) as browser:
        first = browser.active_tab
        viewport = (await first.cdp.page.get_layout_metrics()).css_layout_viewport
        initial = [event for event in events if isinstance(event, CursorStateEvent)]
        assert len(initial) == 1 and initial[0].target_id == first.id
        assert (
            0.4 * viewport.client_width <= initial[0].x <= 0.6 * viewport.client_width
        )
        assert (
            0.4 * viewport.client_height <= initial[0].y <= 0.6 * viewport.client_height
        )
        await browser.mouse.move_to(Point(x=100, y=120))
        second = await browser.open_tab(site)
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
        assert browser.mouse.position_in(second.id) is not None
        opened = next(event for event in events if isinstance(event, TabPressedEvent))
        assert opened.gesture is TabGesture.OPEN and opened.target_id == first.id
        assert opened.from_position == (100, 120)
        await browser.activate_tab(first.id)
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
        second = await browser.open_tab()
        assert first.cdp.session_id != second.cdp.session_id
        assert first.id != second.id
        assert await evaluate(first, "location.href") == "about:blank"
        assert await browser.activate_tab(first.id) is first
        assert connected_target not in {tab.id for tab in await browser.tabs()}
    assert not browser.client.is_connected
    assert first.closed and second.closed
