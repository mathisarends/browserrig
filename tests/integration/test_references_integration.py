from dataclasses import dataclass

import pytest
from harnessed import (
    Agent,
    Plugin,
    PolicyDecision,
    ToolCall,
)
from harnessed.kernel import needs
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Browser,
    BrowserPerception,
    CaptureContent,
    Chrome,
    ElementInfo,
    PageContent,
    Readiness,
    TextContext,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.core import Bounds, ElementPoint
from browserrig.observation import DomRenderer
from browserrig.tools import Actions, KeyboardTools, PointerTools
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_non_dom_refs_deliver_trusted_pointer_and_keyboard_events(site):
    holder = {}
    step = 0

    class Prepare(Plugin, needs=(Browser,)):
        _setup_browser = needs(Browser)

        async def setup(self, _ctx):
            browser = self._setup_browser
            holder["browser"] = browser
            await wait_for_page(browser.active_tab)
            await evaluate(
                browser.active_tab,
                """
                document.body.innerHTML = '<canvas width=800 height=400 tabindex=0></canvas>';
                document.body.style.margin = '0';
                window.shape = {x:50, y:50, width:100, height:40};
                window.received = {pointer:[], keys:[]};
                const canvas = document.querySelector('canvas');
                window.draw = () => {
                    const ctx = canvas.getContext('2d');
                    ctx.clearRect(0,0,800,400);
                    ctx.fillStyle = 'blue';
                    ctx.fillRect(shape.x, shape.y, shape.width, shape.height);
                };
                canvas.addEventListener('pointerdown', event => {
                    received.pointer.push({x:event.clientX,y:event.clientY,trusted:event.isTrusted});
                });
                canvas.addEventListener('keydown', event => {
                    received.keys.push({key:event.key,trusted:event.isTrusted});
                });
                draw();
            """,
            )

    async def respond(_request):
        nonlocal step
        step += 1
        if step == 1:
            # Move the target after observation; its handle must locate it again.
            await evaluate(holder["browser"].active_tab, "shape.x = 200; draw()")
            yield ModelChunk(tool_call=ToolCall("click", {"ref": "drawing/rectangle"}))
        elif step == 2:
            yield ModelChunk(tool_call=ToolCall("send_keys", {"text": "Hi"}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            Chrome(Launch(url=site)),
            Readiness(),
            BrowserPerception(capture=_CanvasCapture(), renderer=DomRenderer()),
            TextContext(),
            Actions(),
            PointerTools(),
            KeyboardTools(),
            Prepare(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        await session.run("Click the observed shape and type Hi")
        received = await evaluate(holder["browser"].active_tab, "received")
    assert received["pointer"] == [{"x": 250, "y": 70, "trusted": True}]
    assert [event["key"] for event in received["keys"]] == ["Shift", "H", "i"]
    assert all(event["trusted"] for event in received["keys"])


class _CanvasCapture:
    async def collect(  # pylint: disable=unused-argument
        self, tab, _report, *, screenshots, region=None, zoom=1, cursor=None
    ):
        shape = Bounds.model_validate(await evaluate(tab, "shape"))
        width, height = await tab.viewport_size()
        return CaptureContent(
            page=PageContent(
                url=tab.url,
                title=tab.title,
                width=width,
                height=height,
                scroll_y=0,
                page_height=height,
                elements=(
                    ElementInfo(
                        ref="drawing/rectangle",
                        role="button",
                        name="Rectangle",
                        bounds=shape,
                    ),
                ),
            ),
            # As with the DOM digest, geometry alone does not change this comparison key.
            fingerprint="rectangle",
            references=_CanvasReferences(),
        )


class _CanvasReferences:
    async def resolve(self, tab, snapshot, ref):
        return _CanvasHandle(snapshot.element(ref), tab)


@dataclass(frozen=True)
class _CanvasHandle:
    element: ElementInfo
    tab: object

    async def locate(self, *, aim=None):
        shape = Bounds.model_validate(await evaluate(self.tab, "shape"))
        fx, fy = aim if aim is not None else (0.5, 0.5)
        return ElementPoint(
            x=shape.x + shape.width * fx, y=shape.y + shape.height * fy, bounds=shape
        )
