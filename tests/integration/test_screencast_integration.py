import asyncio
from base64 import b64decode
from io import BytesIO

import pytest
from harnessed.testing import ScriptedModel
from PIL import Image

from browserrig import Agent, Browser, Chrome, Screencast
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_live_screencast_follows_tabs_and_can_reopen(site):
    agent = Agent(
        model=ScriptedModel([]),
        browser=Chrome.launch(url=site),
        plugins=[Screencast(image_format="png", max_width=320, max_height=240)],
    )
    async with agent.session() as session, asyncio.timeout(20):
        browser = session.scope[Browser]
        screencast = session.scope[Screencast]
        first = browser.active_tab
        async with screencast.open() as frames:
            frame = await anext(frames)
            assert frame.target_id == first.id
            assert frame.mime_type == "image/png"
            with Image.open(BytesIO(b64decode(frame.data))) as image:
                assert image.format == "PNG"
                assert 0 < image.width <= 320
                assert 0 < image.height <= 240

            await evaluate(first, 'document.documentElement.style.background="lime"')
            assert await _shows_green(frames, first.id)

            second = await browser.tabs.open(site + "/other")
            assert (await anext(frames)).target_id == second.id
            await browser.tabs.close(second.id)
            assert (await anext(frames)).target_id == first.id

        assert await anext(frames, None) is None
        async with screencast.open() as reopened:
            assert (await anext(reopened)).target_id == first.id


async def _shows_green(frames, target_id):
    async for frame in frames:
        assert frame.target_id == target_id
        with Image.open(BytesIO(b64decode(frame.data))) as image:
            if image.convert("RGB").getpixel((0, 0)) == (0, 255, 0):
                return True
    return False
