from dataclasses import dataclass

import pytest
from harnessed import (
    Agent,
    Plugin,
    PolicyDecision,
    ToolCall,
)
from harnessed.kernel import PluginScope, needs
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Actions,
    Browser,
    BrowserPerception,
    Chrome,
    InputRuntime,
    KeyboardTools,
    PageCapture,
    PageContent,
    PageReadiness,
    ReferencePointerTools,
    Runtime,
    Targeting,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.core import Bounds, ElementPoint
from browserrig.observation import Target, header
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
            Runtime(),
            InputRuntime(),
            Chrome(Launch(url=site)),
            PageReadiness(),
            BrowserPerception(),
            _CanvasPage(),
            Actions(),
            Targeting(),
            ReferencePointerTools(),
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


class _CanvasPage(Plugin):
    """Read the canvas through the app's own scene, without the DOM."""

    _perception = needs(BrowserPerception)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.use_model(_CanvasModel()))


class _CanvasModel:
    async def collect(self, tab, request):
        del request
        shape = Bounds.model_validate(await evaluate(tab, "shape"))
        viewport = await tab.viewport_size()
        return PageCapture(
            page=PageContent(
                url=tab.url,
                title=tab.title,
                width=viewport.width,
                height=viewport.height,
                scroll_y=0,
                page_height=viewport.height,
                # Geometry is not part of the comparison key, as in the DOM digest.
                targets=(
                    Target(
                        ref="drawing/rectangle",
                        role="button",
                        name="Rectangle",
                        bounds=shape,
                    ),
                ),
            ),
            references=_CanvasReferences(),
        )

    def render(self, snapshot):
        lines = [f'  [{t.ref}] {t.role} "{t.name}"' for t in snapshot.targets]
        return "\n".join([*header(snapshot), *lines])


class _CanvasReferences:
    async def resolve(self, tab, snapshot, ref):
        return _CanvasHandle(snapshot.target(ref), tab)


@dataclass(frozen=True)
class _CanvasHandle:
    target: Target
    tab: object

    async def locate(self, *, aim=None):
        shape = Bounds.model_validate(await evaluate(self.tab, "shape"))
        fx, fy = aim if aim is not None else (0.5, 0.5)
        return ElementPoint(
            x=shape.x + shape.width * fx, y=shape.y + shape.height * fy, bounds=shape
        )
