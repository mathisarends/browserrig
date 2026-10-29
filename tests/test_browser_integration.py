import pytest

from browserrig import ChromeBrowser, ConnectBrowser

pytestmark = pytest.mark.integration


async def test_launch_stable_tabs_and_isolated_connect():
    async with ChromeBrowser() as browser:
        first = browser.active_tab
        assert await first.evaluate("1 + 1") == 2
        endpoint = browser.client.transport.url
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
