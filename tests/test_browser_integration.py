from urllib.parse import urlsplit

import pytest

from browserrig import ChromeBrowser, ConnectBrowser
from browserrig.core.geometry import Point
from browserrig.events import CursorStateEvent

pytestmark = pytest.mark.integration


async def test_tabs_seed_centered_cursor_and_activation_republishes_existing_position(site):
    events = []

    async def emit(event):
        events.append(event)

    async with ChromeBrowser(emit=emit) as browser:
        first = browser.active_tab
        viewport = (await first.cdp.page.get_layout_metrics()).css_layout_viewport
        initial = [event for event in events if isinstance(event, CursorStateEvent)]
        assert len(initial) == 1 and initial[0].target_id == first.id
        assert 0.4 * viewport.client_width <= initial[0].x <= 0.6 * viewport.client_width
        assert 0.4 * viewport.client_height <= initial[0].y <= 0.6 * viewport.client_height
        await first.mouse.move_to(Point(x=100, y=120))
        second = await browser.open_tab(site)
        assert second.mouse.position != Point(x=0, y=0)
        await browser.activate_tab(first.id)
        last = next(event for event in reversed(events) if isinstance(event, CursorStateEvent))
        assert last.target_id == first.id and (last.x, last.y) == (100, 120)


@pytest.mark.parametrize("discovery", [False, True])
async def test_launch_stable_tabs_and_isolated_connect(discovery):
    async with ChromeBrowser() as browser:
        first = browser.active_tab
        assert await first.evaluate("1 + 1") == 2
        endpoint = browser.client.transport.url
        if discovery:
            endpoint = f"http://{urlsplit(endpoint).netloc}/"
        async with ChromeBrowser(ConnectBrowser(endpoint=endpoint)) as connected:
            assert connected.active_tab.id != first.id
            connected_target = connected.active_tab.id
        assert browser.client.is_connected
        assert await first.evaluate("2 + 2") == 4
        second = await browser.open_tab()
        assert first.cdp.session_id != second.cdp.session_id
        assert first.id != second.id
        assert await first.evaluate("location.href") == "about:blank"
        assert await browser.activate_tab(first.id) is first
        assert connected_target not in {tab.id for tab in await browser.tabs()}
    assert not browser.client.is_connected
    assert first.closed and second.closed
