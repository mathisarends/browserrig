import pytest

from browserrig import ChromeBrowser, LaunchBrowser, WebMode, wait_for_page
from browserrig.browser.errors import BrowserError
from browserrig.kinds import ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT, capture

pytestmark = pytest.mark.integration


async def test_frame_extraction_and_old_reference_is_rejected(site):
    async with ChromeBrowser(LaunchBrowser(url=site + "/frames")) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        snapshot = await capture(browser, tab, WebMode(), report)
        inside = next(element for element in snapshot.elements if element.name == "Inside")
        assert inside.frame_id != (await tab.main_frame()).id
        frame = next(frame for frame in await browser.frames(tab) if frame.id == inside.frame_id)
        await frame.call(ELEMENT_SCRIPT, snapshot.id, inside.index, ElementOperation.FOCUS, True)
        await tab.cdp.input.insert_text(text="in an iframe")
        assert await frame.evaluate("document.querySelector('input').value") == "in an iframe"
        await frame.evaluate("document.querySelector('input').remove()")
        with pytest.raises(BrowserError, match="STALE_ELEMENT"):
            await frame.call(
                ELEMENT_SCRIPT, snapshot.id, inside.index, ElementOperation.POINT, None
            )
