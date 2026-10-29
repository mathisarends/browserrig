import pytest
import yaml
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ModelRequestedEvent, ObservationForm, ObservationsIncludedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel

from browserrig import (
    Browser,
    CanvasMode,
    Chrome,
    DomMode,
    Observe,
    Readiness,
    ReadinessOptions,
    browser_plugins,
)
from browserrig.events import (
    ActionFinishedEvent,
    ActivityFinishedEvent,
    NudgeIncludedEvent,
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
    requests = [event for event in result.events if isinstance(event, ModelRequestedEvent)]
    provenance = [event for event in result.events if isinstance(event, ObservationsIncludedEvent)]
    assert len(requests) == len(provenance) == 4
    assert [item.request_id for item in requests] == [item.request_id for item in provenance]
    assert {event.cause_id for event in intervals if event.kind == "llm"} == {
        item.request_id for item in requests
    }
    snapshots = {
        item.observation_id for item in result.events if isinstance(item, ObservationCapturedEvent)
    }
    for included in provenance:
        observations = [item for item in included.observations if item.source == "browser"]
        assert sum(item.form is ObservationForm.FULL for item in observations) == 1
        assert all(len(item.refs) == 1 and item.refs[0] in snapshots for item in observations)


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
            Readiness(CanvasMode()),
            Observe(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Inspect the canvas")
    assert result.text == "Canvas ready"
    assert any(msg.id.startswith("browser-image:") for msg in model.requests[0].messages)
    observations = [e for e in result.events if isinstance(e, ObservationCapturedEvent)]
    assert observations[0].mode == "canvas"


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
                mode=DomMode(), readiness=ReadinessOptions(quiet_ms=50, navigation_min_ms=100)
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Click Nothing")
    assert any(isinstance(e, NudgeQueuedEvent) and e.key == "no_progress" for e in result.events)
    hint = next(
        e for e in result.events if isinstance(e, NudgeQueuedEvent) and e.key == "no_progress"
    )
    receipt = next(
        e
        for e in result.events
        if isinstance(e, NudgeIncludedEvent) and hint.nudge_id in e.nudge_ids
    )
    included = next(
        e
        for e in result.events
        if isinstance(e, ObservationsIncludedEvent) and e.request_id == receipt.request_id
    )
    assert any(
        hint.nudge_id in item.refs and item.form is ObservationForm.FULL
        for item in included.observations
    )
