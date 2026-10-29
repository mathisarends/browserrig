import pytest
import yaml
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel

from browserrig import (
    Browser,
    Chrome,
    FigmaMode,
    Observe,
    Readiness,
    ReadinessOptions,
    WebMode,
    browser_plugins,
)
from browserrig.events import (
    ActionFinishedEvent,
    ActivityFinishedEvent,
    NudgeQueuedEvent,
    ObservationCapturedEvent,
)

pytestmark = pytest.mark.integration


async def test_model_tools_yaml_and_activity(site):
    count = 0

    async def respond(request):
        nonlocal count
        if count == 0:
            result = ToolCall("navigate", {"url": site})
        else:
            state = next(
                (
                    yaml.safe_load(msg.text)
                    for msg in reversed(request.messages)
                    if msg.text.startswith("page:\n")
                ),
                None,
            )
            assert state is not None
            if count == 1:
                email = next((el for el in state["elements"] if el.get("name") == "Email"), None)
                assert email is not None
                result = ToolCall("type_text", {"ref": email["ref"], "text": "person@example.org"})
                assert "never-echo-this" not in str(state)
            elif count == 2:
                button = next((el for el in state["elements"] if el.get("name") == "Submit"), None)
                assert button is not None
                result = ToolCall("click", {"ref": button["ref"]})
            else:
                assert any(el.get("name") == "Done" for el in state["elements"])
                count += 1
                yield ModelChunk(text="Completed")
                return
        count += 1
        yield ModelChunk(tool_call=result)

    model = CallbackModel(respond)
    agent = Agent(
        model=model, plugins=[*browser_plugins(), Approvals(default=PolicyDecision.ALLOW)]
    )
    result = await agent.run("Fill the form and submit", max_steps=5)
    assert result.text == "Completed"
    assert len([event for event in result.events if isinstance(event, ActionFinishedEvent)]) == 3
    intervals = [event for event in result.events if isinstance(event, ActivityFinishedEvent)]
    assert len([event for event in intervals if event.kind == "llm"]) == 4
    assert all(event.at >= event.started_at for event in intervals)


async def test_canvas_mode_native_image(site):
    model = ScriptedModel(["Canvas ready"])

    # Start on a canvas before the first observation: blank about:blank is intentionally not ready.
    class Start(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            await browser.active_tab.navigate(site + "/canvas")

    agent = Agent(
        model=model,
        plugins=[
            Chrome(),
            Start(),
            Readiness(FigmaMode()),
            Observe(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Inspect the canvas")
    assert result.text == "Canvas ready"
    assert any(msg.id.startswith("browser-image:") for msg in model.requests[0].messages)
    observations = [e for e in result.events if isinstance(e, ObservationCapturedEvent)]
    assert observations[0].mode == "figma"


async def test_no_progress_hint_is_derived_from_events(site):
    count = 0

    async def respond(request):
        nonlocal count
        if count == 0:
            result = ToolCall("navigate", {"url": site})
        elif count == 1:
            state = next(
                (
                    yaml.safe_load(msg.text)
                    for msg in reversed(request.messages)
                    if msg.text.startswith("page:\n")
                ),
                None,
            )
            assert state is not None
            element = next((el for el in state["elements"] if el.get("name") == "Nothing"), None)
            assert element is not None
            result = ToolCall("click", {"ref": element["ref"]})
        else:
            assert any("no observable page change" in msg.text for msg in request.messages)
            yield ModelChunk(text="No change detected")
            return
        count += 1
        yield ModelChunk(tool_call=result)

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            *browser_plugins(
                mode=WebMode(), readiness=ReadinessOptions(quiet_ms=50, navigation_min_ms=100)
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Click Nothing")
    assert any(isinstance(e, NudgeQueuedEvent) and e.key == "no_progress" for e in result.events)
