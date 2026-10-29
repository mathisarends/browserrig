import asyncio

import pytest

from browserrig import ChromeBrowser, LaunchBrowser, wait_for_page
from browserrig.browser import DownloadState
from browserrig.events import DownloadCompletedEvent, DownloadStartedEvent

pytestmark = pytest.mark.integration


async def test_scoped_download_has_enum_state_and_namespaced_events(site, tmp_path):
    received = []

    async def collect(event):
        received.append(event)

    async with ChromeBrowser(
        LaunchBrowser(url=site, download_directory=str(tmp_path)), emit=collect
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(browser, tab)
        await tab.evaluate(
            "(() => {const a=document.createElement('a');a.href='/download';"
            "a.download='example.txt';a.click();return true})()"
        )
        async with asyncio.timeout(5):
            while True:
                downloads = await browser.downloads()
                if downloads and downloads[0].state is DownloadState.COMPLETED:
                    break
                await asyncio.sleep(0.02)
        assert downloads[0].received_bytes == len(b"download payload")
        assert any(isinstance(event, DownloadStartedEvent) for event in received)
        assert any(isinstance(event, DownloadCompletedEvent) for event in received)
