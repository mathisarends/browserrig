import asyncio
import base64
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Inject, Plugin, PolicyDecision, SessionLog, SessionState, hook, tool
from harnessed.events import (
    DurableEvent,
    ModelRequestedEvent,
    ObservationRecordedEvent,
    ObservationsIncludedEvent,
    TransientEvent,
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
from browserrig.files.models import Download
from browserrig.nudges import Nudges
from browserrig.observation.capture import CaptureContent
from browserrig.observation.delta import INTRO
from browserrig.observation.extraction import Extraction
from browserrig.observation.models import Element, Snapshot
from browserrig.tools import FileTools, UploadTools
from browserrig.tools.execution import Actions
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


class PageRenderer:
    """Renders the same text for every capture until the test changes the page."""

    def __init__(self):
        self.text = "Page A"

    def instructions(self, _screenshots):
        return ""

    def refs(self):
        return None

    def render(self, _snapshot):
        return self.text


def _agent(
    responses,
    trigger=ScreenshotTrigger.ON_REQUEST,
    retention=None,
    extra=(),
    frames=None,
    skip_unchanged=True,
    after=(),
    renderer=None,
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
                capture=capture,
                renderer=renderer or CustomRenderer(),
                screenshots=Screenshots(trigger=trigger),
            ),
            ImageContext(
                retention or TrimInBatches(max_images=2, min_images=2),
                skip_unchanged=skip_unchanged,
            ),
            Approvals(default=PolicyDecision.ALLOW),
            _Step(),
            *after,
        ],
    )
    return agent, model, capture, holder


class _Step(Plugin):
    """A tool without browser effects, so tests can advance steps."""

    @tool(description="Do nothing.")
    async def step(self) -> str:
        return "Done nothing."


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
        assert _note(model.requests[-1]) == f"Latest captured screenshot: {ids[1]}"
        assert any("Custom view:" in str(message.content) for message in model.requests[0].messages)
        replies = [m for m in model.requests[-1].messages if isinstance(m, ToolMessage)]
        assert all(isinstance(reply.content, str) for reply in replies)


async def test_text_only_observations_and_probes_keep_last_shown_crop_and_no_duplicate_images():
    agent, model, capture, holder = _agent([call("screenshot"), call("step"), "Done"])
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
        [call("step")] * 5 + ["Done"],
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
        assert _note(SimpleNamespace(messages=messages)).startswith("Latest captured screenshot")
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
    # Notes are part of the history too, so whole requests stay prefixes of later ones.
    assert all(
        [(m.id, m.content) for m in requests[i + 1][: len(requests[i])]]
        == [(m.id, m.content) for m in requests[i]]
        for i in (0, 1, 2)
    )
    # Step 5 trims from 4 to 2 images once, then appending resumes.
    assert not shared(requests[3], requests[4])
    assert shared(requests[4], requests[5])


def _steps(count):
    # Distinct calls, so every step gets its own tool call id.
    return [call("step") for _ in range(count)]


def _note(request):
    notes = [m.text for m in request.messages if m.id.endswith(":browser-image")]
    return notes[-1] if notes else None


def _notes(model):
    return [_note(request) for request in model.requests]


async def test_unchanged_screens_are_not_added_again():
    agent, model, _capture, holder = _agent(
        [*_steps(3), "Done"],
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
        [*_steps(2), "Done"],
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
        [*_steps(1), "Done"],
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
        [*_steps(5), "Done"], ScreenshotTrigger.EACH_STEP, UntilCompaction(), extra=(compaction,)
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


async def test_multimodal_observations_use_session_assets_and_survive_saved_state():
    agent, model, _capture, holder = _agent(
        [call("step"), "Done"],
        ScreenshotTrigger.EACH_STEP,
        UntilCompaction(),
        frames=[("same screenshot", 2), ("same screenshot", 2)],
        skip_unchanged=False,
    )
    async with agent.session() as session:
        _browser_ready(holder)
        result = await session.run("Inspect", max_steps=2)
        observations = [
            event
            for event in result.events
            if isinstance(event, ObservationRecordedEvent) and event.observation.source == "browser"
        ]
        assets = [
            part.asset
            for event in observations
            for part in event.observation.content
            if isinstance(part, ImageReference)
        ]
        assert len(assets) == 2 and assets[0] == assets[1]
        assert await session.assets.read(assets[0]) == b"same screenshot"
        request = next(e for e in reversed(result.events) if isinstance(e, ModelRequestedEvent))
        (included,) = [
            e.observations
            for e in result.events
            if isinstance(e, ObservationsIncludedEvent) and e.request_id == request.request_id
        ]
        included = [item for item in included if item.source == "browser"]
        assert len(included) == 2
        for receipt, observation in zip(included, observations, strict=True):
            assert receipt.refs == observation.observation.refs
            assert receipt.turn_id == observation.turn_id
            assert receipt.step == observation.step
            assert receipt.message_id in {message.id for message in request.request.messages}
        assert len(_images(model.requests[-1])) == 2
        saved = session.snapshot().to_json()
    # Saved state carries the retained screenshot bytes, not just their references.
    async with agent.session(state=SessionState.from_json(saved)) as restored:
        assert await restored.assets.read(assets[0]) == b"same screenshot"


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
        # The screenshot was stripped after PrepareRequest; only its note remains.
        included = session.log.last(ObservationsIncludedEvent).observations
        assert [item.source for item in included] == ["browser-image"]
        observe = session.ctx[Observe]
        assert observe.snapshot.geometry is not None
        assert _image_point(observe.coordinate_source(), Point(x=20, y=30)) == Point(x=20, y=30)


async def test_compaction_removes_last_screenshot_on_a_text_only_step():
    fire = iter([False, False, False, True])
    compaction = Compaction(
        trigger=lambda _state: next(fire), summarizer=_Summary(), keep_turns=0, keep_steps=1
    )
    agent, model, _capture, holder = _agent(
        [call("screenshot"), *_steps(2), "Done"],
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
        [call("screenshot"), call("step"), "Done"], extra=(LatestObservationOnly(),)
    )
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=3)
        assert [len(_images(request)) for request in model.requests] == [0, 1, 0]
        included = session.log.last(ObservationsIncludedEvent).observations
        # The screenshot's note left the context with the screenshot.
        assert [item.source for item in included] == ["browser"]
        assert session.ctx[Observe].coordinate_source().geometry is None


def _recorded(results, source):
    return [
        event
        for result in results
        for event in result.events
        if isinstance(event, ObservationRecordedEvent) and event.observation.source == source
    ]


def _visible(request, source):
    return [message for message in request.messages if message.id.endswith(f":{source}")]


async def test_file_state_is_resent_only_after_a_change():
    download = Download(id="d1", filename="report.pdf", url="https://example.org/report.pdf")
    agent, model, _capture, holder = _agent([*_steps(3), "Done"], after=(Actions(), FileTools()))
    async with agent.session() as session:
        browser = _browser_ready(holder)
        browser.downloads = AsyncMock(side_effect=[(), (), (download,), (download,)])
        result = await session.run("Inspect", max_steps=4)
        assert [event.step for event in _recorded([result], "files")] == [1, 3]
        assert [len(_visible(request, "files")) for request in model.requests] == [1, 1, 2, 2]


async def test_file_state_is_resent_when_compaction_removed_the_last_copy():
    fire = iter([False, False, False, True, *[False] * 10])
    compaction = Compaction(
        trigger=lambda _state: next(fire), summarizer=_Summary(), keep_turns=0, keep_steps=1
    )
    agent, model, _capture, holder = _agent(
        [*_steps(4), "Done"], extra=(compaction,), after=(Actions(), FileTools())
    )
    async with agent.session() as session:
        _browser_ready(holder)
        result = await session.run("Inspect", max_steps=5)
        visible = [len(_visible(request, "files")) for request in model.requests]
        # The compacted request lacks the old copy; the next step sends it again.
        assert visible[:3] == [1, 1, 1] and visible[3] == 0 and visible[4] == 1
        assert [event.step for event in _recorded([result], "files")] == [1, 5]


async def test_hint_observations_are_skipped_while_there_is_nothing_to_report():
    agent, model, _capture, holder = _agent([*_steps(3), "Done"], after=(Nudges(),))
    async with agent.session() as session:
        _browser_ready(holder)
        nudges = session.ctx[Nudges]
        first = await session.run("Inspect", max_steps=1)
        await nudges.queue("Inspect the page", key="hint", cause_id="action")
        second = await session.run("Continue", max_steps=3)
        recorded = [event.observation for event in _recorded([first, second], "browser.nudges")]
        # Shown once, cleared once after delivery, then omitted.
        assert [bool(observation.refs) for observation in recorded] == [True, False]
        assert "Inspect the page" in str(recorded[0].content)
        assert len(_visible(model.requests[0], "browser.nudges")) == 0


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


def test_recipe_can_omit_local_file_tools():
    assert not any(
        isinstance(plugin, (FileTools, UploadTools))
        for plugin in browser_plugins(local_files=False)
    )


async def test_unchanged_page_is_not_repeated_while_the_model_still_sees_it():
    renderer = PageRenderer()
    agent, model, _capture, holder = _agent([*_steps(4), "Done"], renderer=renderer)
    async with agent.session() as session:
        _browser_ready(holder)
        first = await session.run("Inspect", max_steps=2)
        renderer.text = "Page B"
        second = await session.run("Continue", max_steps=3)
        recorded = [event.observation.content for event in _recorded([first, second], "browser")]
        assert recorded == ["Page A", "Page B"]
        assert [len(_visible(request, "browser")) for request in model.requests] == [1, 1, 2, 2, 2]


async def test_returning_to_a_page_lists_only_its_changes():
    renderer = PageRenderer()
    first = "\n".join(["# Page A", "", *(f'  [{i}] link "Story {i}"' for i in range(20))])
    agent, _model, _capture, holder = _agent([*_steps(3), "Done"], renderer=renderer)
    async with agent.session() as session:
        tab = _browser_ready(holder).active_tab
        renderer.text, document = first, tab.document_id
        results = [await session.run("Inspect", max_steps=1)]
        renderer.text, tab.document_id = '# Page B\n\n  [1] link "Reply"', "detail"
        results.append(await session.run("Open", max_steps=1))
        # Back on the first document, as bfcache restores it after going back.
        renderer.text, tab.document_id = first.replace('"Story 3"', '"Story 3" focused'), document
        results.append(await session.run("Back", max_steps=1))
    recorded = [event.observation.content for event in _recorded(results, "browser")]
    assert recorded[:2] == [first, '# Page B\n\n  [1] link "Reply"']
    assert recorded[2] == "\n".join(
        ["# Page A", "", INTRO, '- [3] link "Story 3"', '+ [3] link "Story 3" focused']
    )


@pytest.mark.parametrize(
    "renderer,visible",
    [
        # Every capture renders differently, as when the page changed since the last step.
        (None, 2),
        (PageRenderer(), 1),
    ],
)
async def test_each_step_shows_a_changed_page_once_and_an_unchanged_page_not_again(
    renderer, visible
):
    agent, model, _capture, holder = _agent([*_steps(1), "Done"], renderer=renderer)
    async with agent.session() as session:
        _browser_ready(holder)
        await session.run("Inspect", max_steps=2)
    assert len(_visible(model.requests[-1], "browser")) == visible


async def test_page_is_resent_with_a_screenshot_and_after_compaction():
    fire = iter([False, False, False, True, *[False] * 10])
    compaction = Compaction(
        trigger=lambda _state: next(fire), summarizer=_Summary(), keep_turns=0, keep_steps=1
    )
    agent, model, _capture, holder = _agent(
        [call("screenshot"), *_steps(3), "Done"], extra=(compaction,), renderer=PageRenderer()
    )
    async with agent.session() as session:
        _browser_ready(holder)
        result = await session.run("Inspect", max_steps=5)
        # Step 2 carries the requested image; step 5 restores the page compaction removed.
        assert [event.step for event in _recorded([result], "browser")] == [1, 2, 5]
        visible = [len(_visible(request, "browser")) for request in model.requests]
        assert visible[3] == 0 and visible[4] == 1


def test_page_comparison_ignores_new_element_marks():
    observe = Observe()
    button = Element(ref="e1", frame_id="f", backend_id=1, role="button", name="Go", tag="button")
    snapshot = Snapshot(
        id="obs-1",
        tab_id="tab-1",
        document_id="doc-1",
        url="https://example.org/",
        title="Example",
        mode="dom",
        readiness="ready",
        width=1280,
        height=800,
        scroll_y=0,
        fingerprint="page",
        elements=(button,),
    )
    marked = snapshot.model_copy(update={"elements": (button.model_copy(update={"new": True}),)})
    renamed = snapshot.model_copy(
        update={"elements": (button.model_copy(update={"name": "Stop"}),)}
    )
    # pylint: disable=protected-access
    assert observe._page_key(marked) == observe._page_key(snapshot)
    assert observe._page_key(renamed) != observe._page_key(snapshot)
