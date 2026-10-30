import asyncio
import base64
from dataclasses import dataclass, replace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Inject, Plugin, PolicyDecision, SessionLog, SessionState, hook
from harnessed.events import (
    DurableEvent,
    ModelRequestedEvent,
    ObservationRecordedEvent,
    ObservationsIncludedEvent,
    TransientEvent,
    TurnFinishedEvent,
)
from harnessed.hooks import ConfigureRequest, Next, PreStep, StepDecision
from harnessed.models import ImagePart, ImageReference, ModelRequest, ToolMessage
from harnessed.plugins import Approvals, LatestObservationOnly
from harnessed.plugins.compaction import Compaction
from harnessed.testing import ScriptedModel, call

from browserrig import (
    DomRenderer,
    ImageContext,
    Observe,
    Readiness,
    ReadinessOptions,
    ReadinessStrategy,
    Screenshots,
    ScreenshotTrigger,
    TrimInBatches,
    UntilCompaction,
    browser_plugins,
)
from browserrig.core.errors import ReadinessError, StaleElement
from browserrig.core.geometry import Geometry, Point
from browserrig.core.kinds import ObservationKind, ReadinessPhase, ReadinessStage, ReadinessStatus
from browserrig.events import ObservationCapturedEvent, ReadinessStartedEvent
from browserrig.observation.capture import CaptureContent
from browserrig.observation.extraction import Extraction
from browserrig.tools import FileTools, UploadTools
from browserrig.tools.mouse import _image_point
from tests.fakes import FakeChrome
from tests.observations import has_image, image_id


class CountingCapture:
    kind = ObservationKind.DOM
    provides_dom_refs = False

    def __init__(self, frames=None):
        self.captures = []
        # (image, geometry scale) per capture; by default every capture shows a new screen.
        self.frames = frames

    async def collect(  # pylint: disable=unused-argument
        self, tab, _report, *, screenshots, region=None, zoom=1, cursor=None
    ):
        self.captures.append(screenshots)
        image, scale = self._frame() if screenshots else (None, 2)
        return CaptureContent(
            page=Extraction(
                url=tab.url, title="Example", width=800, height=600, scroll_y=0, page_height=600
            ),
            image=base64.b64encode(image.encode()).decode() if image is not None else None,
            geometry=Geometry(x=100, y=50, width=200, height=100, scale=scale)
            if screenshots
            else None,
        )

    def _frame(self):
        count = sum(self.captures)
        return (f"png-{count}", 2) if self.frames is None else self.frames[count - 1]


class CustomRenderer(DomRenderer):
    def render(self, snapshot):
        return f"Custom view: {snapshot.id}"


def _agent(
    responses,
    trigger=ScreenshotTrigger.ON_REQUEST,
    retention=None,
    extra=(),
    frames=None,
    skip_unchanged=True,
):
    holder = {}
    capture = CountingCapture(frames)
    model = ScriptedModel(responses)
    agent = Agent(
        model=model,
        plugins=[
            *extra,
            FakeChrome(holder),
            Readiness(options=ReadinessOptions(navigation_min_ms=0)),
            Observe(
                capture=capture, renderer=CustomRenderer(), screenshots=Screenshots(trigger=trigger)
            ),
            ImageContext(
                retention or TrimInBatches(max_images=2, min_images=2),
                skip_unchanged=skip_unchanged,
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    return agent, model, capture, holder


def _browser_ready(holder):
    browser = holder["browser"]
    browser.tabs = AsyncMock(return_value=())
    return browser


def _images(request):
    return [message for message in request.messages if has_image(message)]


@pytest.mark.parametrize(
    "trigger,counts",
    [
        (ScreenshotTrigger.EACH_STEP, [1, 2, 2, 2]),
        (ScreenshotTrigger.ON_REQUEST, [0, 1, 2, 2]),
    ],
)
async def test_image_fifo_and_one_capture_per_boundary_with_custom_strategies(trigger, counts):
    agent, model, capture, holder = _agent(
        [call("screenshot"), call("screenshot"), call("screenshot"), "Done"], trigger
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=4)
        assert [len(_images(request)) for request in model.requests] == counts
        assert sum(capture.captures) == (4 if trigger == ScreenshotTrigger.EACH_STEP else 3)
        ids = [image_id(message) for message in _images(model.requests[-1])]
        assert len(ids) == len(set(ids)) == 2
        assert ids[0] == image_id(_images(model.requests[-2])[-1])
        note = model.requests[-1].messages[-1]
        assert note.id == "browser-latest-image"
        assert note.text == f"Latest captured screenshot: {ids[1]}"
        assert any("Custom view:" in str(message.content) for message in model.requests[0].messages)
        replies = [m for m in model.requests[-1].messages if isinstance(m, ToolMessage)]
        assert all(isinstance(reply.content, str) for reply in replies)


async def test_text_only_observations_and_probes_keep_last_shown_crop_and_no_duplicate_images():
    agent, model, capture, holder = _agent([call("screenshot"), call("observe"), "Done"])
    async with agent.session() as session:
        browser = _browser_ready(holder)
        await session.run("Inspect", max_steps=3)
        observe = session.ctx[Observe]
        assert observe.snapshot.image is None
        assert _images(model.requests[1])[0].id == _images(model.requests[2])[0].id
        assert _image_point(observe.coordinate_source(), Point(x=20, y=30)) == Point(x=110, y=65)
        assert sum(capture.captures) == 1
        before = observe.snapshot
        await observe.probe(browser.active_tab)
        assert observe.snapshot is before
        assert sum(capture.captures) == 1
        browser.active_tab.document_id = "new-document"
        await observe.capture(screenshots=False)
        with pytest.raises(StaleElement, match="another document"):
            observe.coordinate_source()
        assert (
            sum(
                isinstance(part, ImagePart)
                for message in model.requests[-1].messages
                if not isinstance(message.content, str)
                for part in message.content
            )
            == 1
        )


async def test_image_buffer_is_session_local():
    agent, model, _capture, holder = _agent([call("screenshot"), "First", "Second"])
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("First", max_steps=2)
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Second")
    assert len(_images(model.requests[1])) == 1
    assert not _images(model.requests[2])


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_image_history_size(value):
    with pytest.raises(ValueError, match="positive integers"):
        TrimInBatches(max_images=value)
    with pytest.raises(ValueError, match="positive integers"):
        TrimInBatches(max_images=3, min_images=value)


def test_image_history_trims_to_half_by_default_and_rejects_inverted_bounds():
    assert ImageContext().retention == TrimInBatches(max_images=1, min_images=1)
    assert TrimInBatches(10).min_images == 5
    with pytest.raises(ValueError, match="must not exceed"):
        TrimInBatches(max_images=2, min_images=3)


async def test_images_stay_where_captured_and_keep_the_prompt_prefix_until_a_batch_trim():
    agent, model, _capture, holder = _agent(
        [call("observe")] * 5 + ["Done"],
        ScreenshotTrigger.EACH_STEP,
        TrimInBatches(max_images=4, min_images=2),
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=6)
    requests = [request.messages for request in model.requests]
    for messages in requests:
        # DOM text and screenshot share one immutable observation.
        for message in messages:
            if has_image(message):
                assert "Custom view:" in message.text
                assert "Screenshot " in message.text
        assert messages[-1].id == "browser-latest-image"
    assert [len(_images(request)) for request in model.requests] == [1, 2, 3, 4, 2, 3]

    def prefix(messages):
        # Earlier observations keep their entire content until a batch trim.
        end = max(i for i, m in enumerate(messages) if "Custom view:" in m.text)
        return [(m.id, m.content) for m in messages[:end]]

    def shared(earlier, later):
        stable = prefix(earlier)
        return [(m.id, m.content) for m in later[: len(stable)]] == stable

    # Steps 2-4 only append; earlier images keep their place and caption.
    assert all(shared(requests[i], requests[i + 1]) for i in (1, 2))
    # Step 5 trims from 4 to 2 images once, then appending resumes.
    assert not shared(requests[3], requests[4])
    assert shared(requests[4], requests[5])


def _observes(count):
    # Distinct calls, so every step gets its own tool call id.
    return [call("observe") for _ in range(count)]


def _notes(model):
    return [request.messages[-1].text for request in model.requests]


async def test_unchanged_screens_are_not_added_again():
    agent, model, _capture, holder = _agent(
        [*_observes(3), "Done"],
        ScreenshotTrigger.EACH_STEP,
        TrimInBatches(max_images=4, min_images=4),
        frames=[("a", 2), ("a", 2), ("b", 2), ("b", 2)],
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=4)
    assert [len(_images(request)) for request in model.requests] == [1, 1, 2, 2]
    first, second = (image_id(message) for message in _images(model.requests[-1]))
    assert _notes(model) == [
        f"Latest captured screenshot: {first}",
        f"Latest captured screenshot: {first} (screen unchanged this step)",
        f"Latest captured screenshot: {second}",
        f"Latest captured screenshot: {second} (screen unchanged this step)",
    ]


async def test_same_pixels_with_other_geometry_or_disabled_skipping_are_added():
    agent, model, _capture, holder = _agent(
        [*_observes(2), "Done"],
        ScreenshotTrigger.EACH_STEP,
        TrimInBatches(max_images=4, min_images=4),
        frames=[("a", 2), ("a", 3), ("a", 3)],
        skip_unchanged=False,
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=3)
    assert [len(_images(request)) for request in model.requests] == [1, 2, 3]

    agent, model, _capture, holder = _agent(
        [*_observes(1), "Done"],
        ScreenshotTrigger.EACH_STEP,
        TrimInBatches(max_images=4, min_images=4),
        frames=[("a", 2), ("a", 3)],
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=2)
    assert [len(_images(request)) for request in model.requests] == [1, 2]


class _Summary:
    async def summarize(self, messages, *, max_tokens):  # pylint: disable=unused-argument
        return "summary"


async def test_until_compaction_keeps_images_until_their_steps_are_summarized():
    fire = iter([False, False, False, True, *[False] * 10])
    compaction = Compaction(
        trigger=lambda _state: next(fire), summarizer=_Summary(), keep_turns=0, keep_steps=1
    )
    agent, model, _capture, holder = _agent(
        [*_observes(5), "Done"], ScreenshotTrigger.EACH_STEP, UntilCompaction(), extra=(compaction,)
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=6)
    images = [[message.id for message in _images(request)] for request in model.requests]
    # The request applying the summary drops images with their summarized steps.
    assert [len(ids) for ids in images[:4]] == [1, 2, 3, 2]
    # Steps 1 and 2 were summarized, so their images leave with them; later ones stay in place.
    assert images[4] == images[3] + [images[4][-1]]
    assert images[5] == images[4] + [images[5][-1]]


async def test_multimodal_state_owns_assets_and_provenance_after_original_session_closes():
    agent, model, _capture, holder = _agent(
        [call("observe"), "Done"],
        ScreenshotTrigger.EACH_STEP,
        UntilCompaction(),
        frames=[("same screenshot", 2), ("same screenshot", 2)],
        skip_unchanged=False,
    )
    async with agent.session() as session:
        _browser_ready(holder)
        result = await session.run("Inspect", max_steps=2)
        observations = [
            event for event in result.events if isinstance(event, ObservationRecordedEvent)
        ]
        assets = [
            part.asset
            for event in observations
            for part in event.observation.content
            if isinstance(part, ImageReference)
        ]
        assert len(assets) == 2 and assets[0] == assets[1]
        assert await session.assets.read(assets[0]) == b"same screenshot"
        request = session.log.last(ModelRequestedEvent)
        included = session.log.included_observations(request.request)
        assert len(included) == 2
        for receipt, observation in zip(included, observations, strict=True):
            assert receipt.refs == observation.observation.refs
            assert receipt.turn_id == observation.turn_id
            assert receipt.step == observation.step
            assert receipt.message_id in {message.id for message in request.request.messages}
        assert len(_images(model.requests[-1])) == 2
    state = SessionState.from_json(result.state.to_json())
    async with agent.session(state=state) as restored:
        assert not restored.events
        assert await restored.assets.read(assets[0]) == b"same screenshot"
        assert restored.log.included_observations(request.request) == included
        replay = await restored.log.resolve_request(request.request)
        assert _images(replay) == _images(model.requests[-1])


class StripRequestImages(Plugin):
    @hook(ConfigureRequest)
    async def strip(self, _event: ConfigureRequest, next_: Next[ModelRequest]) -> ModelRequest:
        request = await next_()
        return replace(
            request,
            messages=tuple(
                replace(
                    message,
                    content=tuple(
                        part
                        for part in message.content
                        if not isinstance(part, ImagePart | ImageReference)
                    ),
                )
                if has_image(message)
                else message
                for message in request.messages
            ),
        )


async def test_coordinate_geometry_uses_final_receipts_after_request_image_removal():
    agent, model, _capture, holder = _agent(
        ["Done"], ScreenshotTrigger.EACH_STEP, extra=(StripRequestImages(),)
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect")
        assert not _images(model.requests[0])
        assert session.log.last(ObservationsIncludedEvent).observations == ()
        observe = session.ctx[Observe]
        assert observe.snapshot.geometry is not None
        assert _image_point(observe.coordinate_source(), Point(x=20, y=30)) == Point(x=20, y=30)


async def test_compaction_removes_last_screenshot_on_a_text_only_step():
    fire = iter([False, False, False, True])
    compaction = Compaction(
        trigger=lambda _state: next(fire), summarizer=_Summary(), keep_turns=0, keep_steps=1
    )
    agent, model, _capture, holder = _agent(
        [call("screenshot"), *_observes(2), "Done"],
        retention=UntilCompaction(),
        extra=(compaction,),
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=4)
        assert [len(_images(request)) for request in model.requests] == [0, 1, 1, 0]
        assert session.ctx[Observe].coordinate_source().geometry is None


async def test_latest_observation_only_is_an_explicit_policy_with_native_image_lifecycle():
    agent, model, _capture, holder = _agent(
        [call("screenshot"), call("observe"), "Done"], extra=(LatestObservationOnly(),)
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=3)
        assert [len(_images(request)) for request in model.requests] == [0, 1, 0]
        included = session.log.last(ObservationsIncludedEvent).observations
        assert len(included) == 1 and included[0].source == "browser"
        assert session.ctx[Observe].coordinate_source().geometry is None


class Probe(ReadinessStrategy):
    budget = 0.01

    def __init__(self, context, policy):
        super().__init__(context.tab, context.options)
        self.context = context
        self.policy = policy

    async def check(self):
        self.policy.checks.append((self.context.tab.document_id, self.context.stage))
        if self.policy.change_document:
            self.context.tab.document_id = "preview"
            self.context.tab.url = "file:///preview.pdf"
            self.policy.change_document = False
        return self.policy.ready

    def timeout_status(self):
        return ReadinessStatus.FAILED


class Policy:
    def __init__(self, *, ready=True, change_document=False):
        self.ready = ready
        self.change_document = change_document
        self.checks = []

    def create(self, context):
        return Probe(context, self)


async def test_initial_per_document_and_ongoing_readiness_with_stream_stage():
    holder = {}
    initial, ongoing = Policy(), Policy()
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(initial=initial, ongoing=ongoing),
        ],
    )
    async with agent.session() as session:
        readiness = session.ctx[Readiness]
        tab = holder["browser"].active_tab
        await readiness.wait(tab)
        await readiness.wait(tab, phase=ReadinessPhase.AFTER_ACTION)
        tab.document_id = "doc-2"
        await readiness.wait(tab, phase=ReadinessPhase.NAVIGATION)
        readiness.invalidate(tab)
        await readiness.wait(tab)
        tab.document_id, tab.url = "preview", "file:///preview.pdf"
        await readiness.wait(tab)
        assert [doc for doc, _ in initial.checks] == ["doc-1", "doc-2", "doc-2", "preview"]
        assert len(ongoing.checks) == 1
        starts = [e for e in session.events if isinstance(e, ReadinessStartedEvent)]
        assert [(e.stage, e.phase) for e in starts[:3]] == [
            (ReadinessStage.INITIAL, ReadinessPhase.OBSERVATION),
            (ReadinessStage.ONGOING, ReadinessPhase.AFTER_ACTION),
            (ReadinessStage.INITIAL, ReadinessPhase.NAVIGATION),
        ]


async def test_failed_initial_retries_and_navigation_reselects_policy():
    holder = {}
    app = Policy(ready=False)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(initial=app),
        ],
    )
    async with agent.session() as session:
        readiness = session.ctx[Readiness]
        tab = holder["browser"].active_tab
        for _ in range(2):
            with pytest.raises(ReadinessError):
                await readiness.wait(tab)
        assert len(app.checks) == 2
        app.ready, app.change_document = True, True
        report = await readiness.wait(tab)
        assert report.document_id == "preview" and report.status == ReadinessStatus.READY
        assert app.checks[-1] == ("preview", ReadinessStage.INITIAL)


async def test_invalidation_cancels_old_wait_and_starts_a_fresh_initial_probe():
    holder = {}
    entered = asyncio.Event()
    attempts = 0

    class WaitingProbe(Probe):
        async def check(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                entered.set()
                await asyncio.Event().wait()
            return True

    class WaitingPolicy(Policy):
        def create(self, context):
            return WaitingProbe(context, self)

    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(initial=WaitingPolicy()),
        ],
    )
    async with agent.session() as session:
        readiness = session.ctx[Readiness]
        tab = holder["browser"].active_tab
        old = asyncio.create_task(readiness.wait(tab))
        await entered.wait()
        readiness.invalidate(tab)
        report = await readiness.wait(tab)
        with pytest.raises(asyncio.CancelledError):
            await old
        assert attempts == 2
        assert report.stage == ReadinessStage.INITIAL


@dataclass(frozen=True)
class AppFact(DurableEvent):
    type: Literal["test.app.fact"] = "test.app.fact"


@dataclass(frozen=True)
class AppProgress(TransientEvent):
    type: Literal["test.app.progress"] = "test.app.progress"


class AppEvents(Plugin):
    events = (AppFact, AppProgress)

    @hook(PreStep)
    async def emit(self, _event: PreStep, next_: Next[StepDecision], log: Inject[SessionLog]):
        await log.emit(AppFact())
        await log.emit(AppProgress())
        return await next_()


async def test_native_stream_forwards_custom_events_and_browser_readiness_without_image_data():
    agent, _model, _capture, holder = _agent(
        ["Done"], ScreenshotTrigger.EACH_STEP, extra=(AppEvents(),)
    )
    async with agent.session() as session:
        _browser_ready(holder)
        streamed = [event async for event in session.stream("Inspect")]
        assert any(isinstance(e, AppFact) for e in streamed)
        assert any(isinstance(e, AppProgress) for e in streamed)
        assert any(isinstance(e, ReadinessStartedEvent) for e in streamed)
        observations = [e for e in streamed if isinstance(e, ObservationCapturedEvent)]
        assert len(observations) == 1 and not hasattr(observations[0], "image")
        result = next(event.result for event in streamed if isinstance(event, TurnFinishedEvent))
        assert any(isinstance(e, AppFact) for e in result.events)
        assert not any(isinstance(e, AppProgress) for e in result.events)
        assert not session.events


def test_recipe_can_omit_local_file_tools():
    assert not any(
        isinstance(plugin, (FileTools, UploadTools))
        for plugin in browser_plugins(local_files=False)
    )
