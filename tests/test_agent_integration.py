import pytest
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ModelRequestedEvent, ObservationForm, ObservationsIncludedEvent
from harnessed.models import ImagePart, ModelChunk, ToolReply
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel, call

from browserrig import (
    Browser,
    CanvasMode,
    Chrome,
    DomMode,
    ImageContext,
    LaunchBrowser,
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
from tests.observations import all_states, is_observation, latest, parse

pytestmark = pytest.mark.integration


async def test_screenshots_are_requested_as_tools_and_markdown_is_text_only(site, monkeypatch):
    captures = 0

    class CountScreenshots(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            page_type = type(browser.active_tab.cdp.page)
            original = page_type.capture_screenshot

            async def counted(page, *args, **kwargs):
                nonlocal captures
                captures += 1
                return await original(page, *args, **kwargs)

            monkeypatch.setattr(page_type, "capture_screenshot", counted)

    model = ScriptedModel(
        [call("screenshot"), call("observe"), call("extract_content"), call("screenshot"), "Done"]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(LaunchBrowser(url=site)),
            CountScreenshots(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Inspect the page on demand", max_steps=5)
    assert result.text == "Done"
    assert captures == 2
    assert {"screenshot", "extract_content", "observe"} <= {
        item.name for item in model.requests[0].tools
    }
    assert not any(
        isinstance(part, ImagePart)
        for message in model.requests[0].messages
        if not isinstance(message.content, str)
        for part in message.content
    )
    for index, request in enumerate(model.requests):
        states = all_states(request.messages)
        assert states and all("text" not in state for state in states)
        images = [
            message for message in request.messages if message.id.startswith("browser-image:")
        ]
        assert len(images) == (1 if index >= 1 else 0)
        if not images:
            continue
        assert any(isinstance(part, ImagePart) for part in images[0].content)
        assert latest(request.messages)["elements"]
    replies = [msg for msg in model.requests[-1].messages if isinstance(msg, ToolReply)]
    assert len(replies) == 4
    assert all(not reply.is_error for reply in replies)
    assert all(isinstance(reply.content, str) for reply in replies)
    assert isinstance(replies[1].content, str) and is_observation(replies[1].text)
    assert "text" not in parse(replies[1].text)
    assert isinstance(replies[2].content, str) and "# Test form" in replies[2].text


async def test_model_tools_yaml_and_activity(site):
    count = 0

    async def respond(request):
        nonlocal count
        if count == 0:
            result = ToolCall("navigate", {"url": site})
        else:
            state = latest(request.messages)
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


@pytest.mark.parametrize("mode", [DomMode(screenshots=True), CanvasMode()])
async def test_visual_modes_native_image(site, mode):
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
            Readiness(mode),
            Observe(mode),
            ImageContext(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Inspect the canvas")
    assert result.text == "Canvas ready"
    assert any(msg.id.startswith("browser-image:") for msg in model.requests[0].messages)
    observations = [e for e in result.events if isinstance(e, ObservationCapturedEvent)]
    assert observations[0].mode == mode.kind


async def test_no_progress_hint_is_derived_from_events(site):
    count = 0

    async def respond(request):
        nonlocal count
        if count == 0:
            result = ToolCall("navigate", {"url": site})
        elif count == 1:
            state = latest(request.messages)
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
