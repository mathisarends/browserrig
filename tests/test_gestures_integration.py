import pytest
import yaml
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Browser, LaunchBrowser, browser_plugins
from browserrig.kinds import DragMode

pytestmark = pytest.mark.integration


async def _perform(site, name, arguments):
    holder = {}
    count = 0

    class Access(Plugin):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            holder["browser"] = browser

    async def respond(request):
        nonlocal count
        if count == 0:
            state = next(
                (
                    yaml.safe_load(msg.text)
                    for msg in reversed(request.messages)
                    if msg.text.startswith("page:\n")
                ),
                None,
            )
            assert state is not None
            count += 1
            yield ModelChunk(tool_call=ToolCall(name, arguments(state)))
        else:
            yield ModelChunk(text="Gesture completed")

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            *browser_plugins(LaunchBrowser(url=site + "/gestures")),
            Access(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Perform one gesture")
        assert result.text == "Gesture completed"
        receipts = [
            event for event in session.events if isinstance(event, ToolExecutionFinishedEvent)
        ]
        assert receipts and all(not event.result.is_error for event in receipts)
        # The test fixture stores counters in its main world. Production extraction
        # deliberately runs in an isolated world, where page-owned globals are absent.
        state = await holder["browser"].active_tab.cdp.runtime.evaluate(
            expression="({doubles:window.doubles,details:window.details,"
            "native:window.nativeDrop,pointer:window.pointerDrop})",
            return_by_value=True,
        )
        return state.result.value


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


@pytest.mark.parametrize("mode", [DragMode.POINTER, DragMode.HTML5])
@pytest.mark.parametrize("coordinates", [False, True])
async def test_drag_pointer_and_html5_transfer(site, mode, coordinates):
    def arguments(state):
        if coordinates:
            y = 140 if mode is DragMode.HTML5 else 290
            return {
                "start": {"x": 70, "y": y},
                "end": {"x": 350, "y": y},
                "mode": mode,
                "duration": 0.1,
            }
        prefix = "Native" if mode is DragMode.HTML5 else "Pointer"
        refs = {e["name"]: e["ref"] for e in state["elements"]}
        return {
            "source_ref": refs[f"{prefix} source"],
            "target_ref": refs[f"{prefix} target"],
            "duration": 0.1,
        }

    state = await _perform(site, "drag_at" if coordinates else "drag", arguments)
    assert state["native"] == "payload" if mode is DragMode.HTML5 else state["pointer"] is True
