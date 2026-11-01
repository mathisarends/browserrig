import asyncio

import pytest
from harnessed import (
    Agent,
    Context,
    Inject,
    Plugin,
    PluginInstructions,
    PolicyDecision,
    SystemPrompt,
    ToolCall,
)
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Browser, ChromeBrowser, Launch, browser_plugins
from browserrig.choreography import Stage
from browserrig.core import Point
from browserrig.events import CursorStateEvent
from browserrig.input import HumanMotor
from tests.observations import latest

pytestmark = pytest.mark.integration


async def evaluate(tab, expression):
    # Fixture counters and DataTransfer listeners live in the page's main world.
    result = await tab.cdp.runtime.evaluate(expression=expression, return_by_value=True)
    assert result.exception_details is None
    return result.result.value


@pytest.mark.parametrize("coordinates", [False, True])
async def test_double_click_dispatches_native_detail_and_dblclick(site, coordinates):
    def arguments(state):
        if coordinates:
            return {"x": 70, "y": 40, "count": 2}
        ref = next(e["ref"] for e in state["elements"] if e["name"] == "Double")
        return {"ref": ref, "count": 2}

    state = await _perform(site, "click_at" if coordinates else "click", arguments)
    assert state["doubles"] == 1
    assert state["details"] == [1, 2]


@pytest.mark.parametrize("coordinates", [False, True])
async def test_right_click_dispatches_native_contextmenu_without_a_left_click(
    site, coordinates
):
    def arguments(state):
        if coordinates:
            return {"x": 70, "y": 40, "button": "right"}
        ref = next(e["ref"] for e in state["elements"] if e["name"] == "Double")
        return {"ref": ref, "button": "right"}

    state = await _perform(site, "click_at" if coordinates else "click", arguments)
    assert state["contexts"] == [{"button": 2, "trusted": True}]
    assert state["details"] == [] and state["doubles"] == 0


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("coordinates", [False, True])
async def test_drag_pointer_and_html5_transfer(site, native, coordinates):
    def arguments(state):
        if coordinates:
            y = 140 if native else 290
            return {
                "start": {"x": 70, "y": y},
                "end": {"x": 350, "y": y},
                "duration": 0.1,
            }
        prefix = "Native" if native else "Pointer"
        refs = {e["name"]: e["ref"] for e in state["elements"]}
        return {
            "source_ref": refs[f"{prefix} source"],
            "target_ref": refs[f"{prefix} target"],
            "duration": 0.1,
        }

    state = await _perform(site, "drag_at" if coordinates else "drag", arguments)
    assert state["native"] == "payload" if native else state["pointer"] is True


@pytest.mark.parametrize("prevented", [False, True])
async def test_drag_uses_browser_behavior_for_draggable_ancestor(site, prevented):
    async with ChromeBrowser(Launch(url=site + "/gestures")) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """(() => {
                const source = document.querySelector('#native');
                source.innerHTML =
                    '<span style="display:block;width:100%;height:100%">Child</span>';
                window.dragStarts = 0;
                source.addEventListener('dragstart', e => {
                    window.dragStarts++;
                    if (PREVENTED) e.preventDefault();
                });
            })()""".replace("PREVENTED", str(prevented).lower()),
        )
        assert (
            await evaluate(tab, "document.elementFromPoint(70, 140).draggable") is False
        )
        await browser.mouse.drag(
            start=Point(x=70, y=140), end=Point(x=350, y=140), duration=0.1
        )
        assert await evaluate(tab, "window.dragStarts") == 1
        assert await evaluate(tab, "window.nativeDrop") == (
            "" if prevented else "payload"
        )


async def test_cancelled_native_drag_does_not_drop_and_allows_next_gesture(site):
    reached_target = asyncio.Event()

    async def emit(event):
        if (
            isinstance(event, CursorStateEvent)
            and event.buttons == 1
            and event.x == 350
        ):
            reached_target.set()
            await asyncio.Event().wait()

    async with ChromeBrowser(Launch(url=site + "/gestures"), emit=emit) as browser:
        # Paced and reported, so the drag can be held right at its target.
        browser.input.pace(HumanMotor())
        browser.input.present(Stage(lambda: browser.input.action_id))
        tab = browser.active_tab
        await evaluate(
            tab,
            """window.dragEnds = [];
            document.querySelector('#native').addEventListener('dragend', e => {
                window.dragEnds.push(e.dataTransfer.dropEffect);
            });""",
        )
        task = asyncio.create_task(
            browser.mouse.drag(
                start=Point(x=70, y=140), end=Point(x=350, y=140), duration=0.1
            )
        )
        try:
            await asyncio.wait_for(reached_target.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 30)
        assert await evaluate(tab, "window.nativeDrop") == ""
        assert await evaluate(tab, "window.dragEnds") == ["none"]
        await browser.mouse.click(Point(x=70, y=40))
        assert await evaluate(tab, "window.details") == [1]


async def _perform(site, name, arguments):
    holder = {}
    count = 0

    class Access(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            holder["browser"] = browser

    async def respond(request):
        nonlocal count
        if count == 0:
            state = latest(request.messages)
            assert state is not None
            count += 1
            yield ModelChunk(tool_call=ToolCall(name, arguments(state)))
        else:
            yield ModelChunk(text="Gesture completed")

    agent = Agent(
        system_prompt=SystemPrompt(PluginInstructions()),
        model=CallbackModel(respond),
        plugins=[
            *browser_plugins(browser=Launch(url=site + "/gestures")),
            Access(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Perform one gesture")
        assert result.text == "Gesture completed"
        receipts = [
            event
            for event in result.events
            if isinstance(event, ToolExecutionFinishedEvent)
        ]
        assert receipts and all(not event.result.is_error for event in receipts)
        # The test fixture stores counters in its main world. Production extraction
        # deliberately runs in an isolated world, where page-owned globals are absent.
        state = await holder["browser"].active_tab.cdp.runtime.evaluate(
            expression="({doubles:window.doubles,details:window.details,"
            "native:window.nativeDrop,pointer:window.pointerDrop,contexts:window.contexts})",
            return_by_value=True,
        )
        return state.result.value
