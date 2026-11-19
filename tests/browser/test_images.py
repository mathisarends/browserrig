from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify import CDPCommandError, CDPConnectionError

from browserrig.browser import Tab, screenshot
from browserrig.core import BrowserError


@pytest.mark.parametrize("overlays", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        CDPCommandError("Page.captureScreenshot", -32000, "Unavailable"),
        CDPConnectionError("Connection closed"),
    ],
)
async def test_screenshot_preserves_the_cdp_failure_as_cause(overlays, error):
    capture = AsyncMock(side_effect=error)
    tab = Tab("tab", SimpleNamespace(page=SimpleNamespace(capture_screenshot=capture)))

    with pytest.raises(BrowserError) as failure:
        await screenshot(tab, overlays=overlays)

    assert failure.value.__cause__ is error
    capture.assert_awaited_once()
