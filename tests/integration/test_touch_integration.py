import asyncio
import base64
from io import BytesIO

import pytest
from cdpify.domains.input import Input as CdpInput
from harnessed import Agent
from harnessed.models import ModelChunk, ToolCall
from harnessed.testing import CallbackModel
from PIL import Image

from browserrig import (
    Actions,
    Browser,
    BrowserPerception,
    Choreography,
    Chrome,
    ChromeBrowser,
    DeviceRuntime,
    DomPage,
    KeyboardInput,
    KeyboardTools,
    PageReadiness,
    Point,
    ReferenceTouchTools,
    Runtime,
    Screenshots,
    ScreenshotTools,
    ScreenshotTrigger,
    Targeting,
    Touch,
    TouchInput,
    TouchTools,
)
from browserrig.browser import Launch
from tests.javascript import evaluate
from tests.observations import latest

pytestmark = pytest.mark.integration


class Phone:
    async def apply(self, cdp, *, frame):
        if not frame:
            await cdp.emulation.set_device_metrics_override(
                width=390, height=700, mobile=True, device_scale_factor=3
            )
            await cdp.emulation.set_touch_emulation_enabled(enabled=True)


async def test_touch_session_scrolls_and_fills_form_without_mouse(site, monkeypatch):
    async def unexpected_mouse(*_args, **_kwargs):
        pytest.fail("Touch session dispatched mouse or wheel input")

    monkeypatch.setattr(CdpInput, "dispatch_mouse_event", unexpected_mouse)
    step = 0

    async def respond(request):
        nonlocal step
        step += 1
        if step == 1:
            region = {"x": 75, "y": 85, "width": 90, "height": 75}
            yield ModelChunk(tool_call=ToolCall("screenshot", {"region": region}))
        elif step == 2:
            source = session.scope[BrowserPerception].coordinate_source()
            assert source.geometry is not None and source.image is not None
            x, y = 35 * source.geometry.scale, 25 * source.geometry.scale
            with Image.open(BytesIO(base64.b64decode(source.image))) as crop:
                assert crop.convert("RGB").getpixel((int(x), int(y))) == (0, 255, 0)
            yield ModelChunk(tool_call=ToolCall("tap_at", {"x": x, "y": y}))
        elif step == 3:
            assert await evaluate(tab, "document.body.dataset.tapped") == "touch"
            yield ModelChunk(
                tool_call=ToolCall(
                    "swipe_at",
                    {"start": {"x": 280, "y": 550}, "end": {"x": 280, "y": 240}},
                )
            )
        elif step == 4:
            assert await evaluate(tab, "document.scrollingElement.scrollTop") > 0
            state = latest(request.messages)
            ref = next(
                (e["ref"] for e in state["elements"] if e["name"] == "City"), None
            )
            assert ref is not None
            yield ModelChunk(tool_call=ToolCall("tap", {"ref": ref}))
        elif step == 5:
            assert await evaluate(tab, "document.activeElement.id") == "city"
            yield ModelChunk(tool_call=ToolCall("send_keys", {"text": "Berlin"}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            Runtime(),
            Chrome.launch(session_setup=(Phone(),)),
            DeviceRuntime(),
            KeyboardInput(),
            TouchInput(),
            PageReadiness(),
            BrowserPerception(text="full"),
            DomPage(),
            Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            Actions(),
            Targeting(),
            ReferenceTouchTools(),
            TouchTools(),
            KeyboardTools(),
            ScreenshotTools(),
            Choreography(),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = await browser.tabs.open(site)
        await browser.tabs.activate(tab.id)
        await evaluate(
            tab,
            """document.head.innerHTML = '<meta name="viewport" content="width=device-width">';
            document.body.innerHTML = '<button>Tap</button>'
              + '<input aria-label="City" id="city" style="position:fixed;top:190px">'
              + '<div style="height:2200px"></div>';
            const button = document.querySelector('button');
            button.style.cssText = 'position:absolute;left:90px;top:160px';
            button.style.background = button.style.color = 'lime';
            button.onpointerdown = e => document.body.dataset.tapped = e.pointerType;
            window.scrollTo(0, 60)""",
        )
        result = await session.run("Use the phone form", max_steps=7)
        assert result.text == "Done"
        assert await evaluate(tab, "document.querySelector('#city').value") == "Berlin"


async def test_cancelled_swipe_releases_original_touch_contact(site):
    async with ChromeBrowser(Launch(url=site, session_setup=(Phone(),))) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """document.head.innerHTML = '<meta name="viewport" content="width=device-width">';
            document.body.style.touchAction = 'none';
            document.body.dataset.events = '';
            for (const type of ['touchstart', 'touchcancel', 'touchend']) {
                document.addEventListener(type, () => document.body.dataset.events += type + ' ');
            }""",
        )
        touch = Touch(browser.input_targets.focused)
        point = Point(x=80, y=80)
        swipe = asyncio.create_task(
            touch.swipe(point, Point(x=160, y=120), duration_seconds=3)
        )
        try:
            async with asyncio.timeout(3):
                while not await evaluate(tab, "document.body.dataset.events"):
                    await asyncio.sleep(0.01)
        finally:
            swipe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(swipe, 5)
        await touch.tap(point)
        assert (
            await evaluate(tab, "document.body.dataset.events")
            == "touchstart touchcancel touchstart touchend "
        )
