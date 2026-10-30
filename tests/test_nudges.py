from dataclasses import replace

import pytest
from harnessed import Agent, Context, Inject, Plugin, SessionState, hook
from harnessed.events import (
    IncludedObservation,
    ModelRequestedEvent,
    ObservationsIncludedEvent,
)
from harnessed.hooks import ConfigureRequest, Next, PreStep, StepDecision
from harnessed.models import ModelInfo, ModelRequest, UserMessage
from harnessed.testing import ScriptedModel

from browserrig import Nudges
from browserrig.events import (
    ActionFinishedEvent,
    ActionStartedEvent,
    NudgeIncludedEvent,
    NudgeQueuedEvent,
    ObservationCapturedEvent,
    PageState,
    TabClosedEvent,
)
from browserrig.observation.models import Snapshot
from tests.fakes import FakeChrome


@pytest.mark.parametrize(
    "after_url,document,prepared,expected",
    [
        ("https://example.org/", "doc-1", False, True),
        ("https://example.org/#changed", "doc-1", False, False),
        ("https://example.org/?changed=1", "doc-1", False, False),
        ("https://example.org/", "doc-2", False, False),
        ("https://example.org/", "doc-1", True, False),
    ],
)
async def test_scroll_nudge_requires_exact_same_url_document_and_unrequested_scroll(
    after_url, document, prepared, expected
):
    holder = {}

    # Declare action/observation facts in the producer, just as a real tool plugin does.
    class Producer(FakeChrome):
        events = (ActionStartedEvent, ActionFinishedEvent, ObservationCapturedEvent)

    agent = Agent(model=ScriptedModel(["ok"]), plugins=[Producer(holder), Nudges()])
    async with agent.session() as session:
        await session.emit(ActionStartedEvent(action_id="click-1", kind="click", target_id="tab-1"))
        await session.emit(
            ActionFinishedEvent(
                action_id="click-1",
                kind="click",
                target_id="tab-1",
                document_id=document,
                before=PageState(
                    url="https://example.org/", document_id="doc-1", fingerprint="before"
                ),
                after_url=after_url,
                prepared_scroll=prepared,
            )
        )
        await session.emit(
            ObservationCapturedEvent(
                observation_id="obs-1",
                target_id="tab-1",
                document_id=document,
                url=after_url,
                fingerprint="after",
                scroll_y=640,
                mode="dom",
                readiness="ready",
            )
        )
        actual = any(
            isinstance(e, NudgeQueuedEvent) and e.key == "unexpected_scroll" for e in session.events
        )
        assert actual is expected


async def test_pending_actions_are_separate_per_tab_and_closed_tabs_are_forgotten():
    class Producer(FakeChrome):
        events = (ActionStartedEvent, ActionFinishedEvent, ObservationCapturedEvent, TabClosedEvent)

    agent = Agent(model=ScriptedModel(["unused"]), plugins=[Producer({}), Nudges()])
    async with agent.session() as session:
        for target in ("first", "second"):
            await session.emit(ActionStartedEvent(action_id=target, kind="click", target_id=target))
            await session.emit(
                ActionFinishedEvent(
                    action_id=target,
                    kind="click",
                    target_id=target,
                    before=PageState(url="https://example.org/", document_id="doc"),
                    after_url="https://example.org/",
                )
            )
        await session.emit(TabClosedEvent(target_id="first"))
        for target in ("first", "second"):
            await session.emit(
                ObservationCapturedEvent(
                    observation_id=target,
                    target_id=target,
                    document_id="doc",
                    url="https://example.org/",
                    fingerprint="changed",
                    scroll_y=500,
                    mode="dom",
                    readiness="ready",
                )
            )
        scrolls = [
            event
            for event in session.events
            if isinstance(event, NudgeQueuedEvent) and event.key == "unexpected_scroll"
        ]
        assert len(scrolls) == 1 and scrolls[0].target_id == "second"


@pytest.mark.parametrize(
    "source,matching_ref,delivered",
    [
        ("browser.nudges", True, True),
        ("other", True, False),
        ("browser.nudges", False, False),
    ],
)
async def test_hint_acknowledgement_requires_matching_provenance(source, matching_ref, delivered):
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Nudges(), _Access(holder)],
    )
    async with agent.session() as session:
        nudges = holder["nudges"]
        await nudges.queue("Inspect the page", key="hint", cause_id="action")
        observation = await nudges.project(_snapshot())
        (nudge_id,) = observation.refs
        # Text coincidence cannot acknowledge delivery, even in a submitted request.
        await session.emit(
            ModelRequestedEvent(
                ModelRequest(messages=(UserMessage(nudge_id),)),
                model=ModelInfo(name="test"),
                request_id="request",
            )
        )
        assert (await nudges.project(_snapshot())).refs == (nudge_id,)
        included = ObservationsIncludedEvent(
            request_id="request",
            observations=(
                IncludedObservation(
                    source,
                    (nudge_id if matching_ref else "unknown",),
                    turn_id="turn",
                    step=1,
                    message_id="message",
                ),
            ),
        )
        await session.emit(included)
        await session.emit(included)
        receipts = [event for event in session.events if isinstance(event, NudgeIncludedEvent)]
        assert len(receipts) == int(delivered)
        assert (await nudges.project(_snapshot())).refs == (() if delivered else (nudge_id,))
        if delivered:
            assert receipts[0].request_id == "request"


async def test_hint_provenance_survives_state_but_pending_browser_hints_start_fresh():
    holder = {}

    class Hints(Plugin, needs=(Nudges,)):
        @hook(PreStep)
        async def observe_hints(
            self,
            event: PreStep,
            next_: Next[StepDecision],
            nudges: Inject[Nudges],
        ) -> StepDecision:
            event.session.observe(await nudges.project(_snapshot()))
            return await next_()

    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Nudges(max_hints=1),
            _Access(holder),
            Hints(),
        ],
    )
    async with agent.session() as session:
        nudges = holder["nudges"]
        await nudges.queue("First hint", key="first", cause_id="first-action")
        await nudges.queue("Second hint", key="second", cause_id="second-action")
        result = await session.run("Inspect")
        request = next(event for event in result.events if isinstance(event, ModelRequestedEvent))
        provenance = session.log.included_observations(request.request)
        (receipt,) = [event for event in result.events if isinstance(event, NudgeIncludedEvent)]
        assert receipt.request_id == request.request_id
        assert provenance == (
            IncludedObservation(
                "browser.nudges",
                receipt.nudge_ids,
                turn_id=provenance[0].turn_id,
                step=1,
                message_id=provenance[0].message_id,
            ),
        )
        assert "Second hint" in (await nudges.project(_snapshot())).content
    state = SessionState.from_json(result.state.to_json())
    async with agent.session(state=state) as restored:
        assert restored.log.included_observations(request.request) == provenance
        remaining = await holder["nudges"].project(_snapshot())
        assert not remaining.refs
        assert "Second hint" not in remaining.content
        assert "First hint" not in remaining.content


@pytest.mark.parametrize("transform", ["keep", "drop", "redact"])
async def test_hints_stay_queued_until_the_unchanged_observation_is_submitted(transform):
    holder = {}

    class Hints(Plugin, needs=(Nudges,)):
        @hook(PreStep)
        async def project(self, event: PreStep, next_: Next[StepDecision], nudges: Inject[Nudges]):
            event.session.observe(await nudges.project(_snapshot()))
            return await next_()

        @hook(ConfigureRequest)
        async def change(self, event: ConfigureRequest, next_: Next[ModelRequest]):
            request = await next_()
            ids = {
                item.message_id
                for item in event.session.log.included_observations(request)
                if item.source == "browser.nudges"
            }
            if transform == "drop":
                return replace(
                    request, messages=tuple(m for m in request.messages if m.id not in ids)
                )
            if transform == "redact":
                return replace(
                    request,
                    messages=tuple(
                        replace(message, content="Redacted hint") if message.id in ids else message
                        for message in request.messages
                    ),
                )
            return request

    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Nudges(), _Access(holder), Hints()],
    )
    async with agent.session() as session:
        nudges = holder["nudges"]
        await nudges.queue("Inspect the page", key="hint", cause_id="action")
        (nudge_id,) = (await nudges.project(_snapshot())).refs
        result = await session.run("Inspect")
        receipts = [event for event in result.events if isinstance(event, NudgeIncludedEvent)]
        delivered = transform == "keep"
        assert len(receipts) == int(delivered)
        assert (await nudges.project(_snapshot())).refs == (() if delivered else (nudge_id,))


class _Access(Plugin, needs=(Nudges,)):
    nudges: Inject[Nudges]

    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, _ctx: Context):
        self.holder["nudges"] = self.nudges


def _snapshot():
    return Snapshot(
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
    )
