import pytest
from harnessed import Agent, Context, Inject, Plugin, hook
from harnessed.events import (
    IncludedObservation,
    ModelRequestedEvent,
    ObservationForm,
    ObservationsIncludedEvent,
)
from harnessed.hooks import Next, PreStep, StepDecision
from harnessed.models import ModelRequest, User
from harnessed.plugins import JsonlSessions
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
    "source,form,matching_ref,delivered",
    [
        ("browser.nudges", ObservationForm.FULL, True, True),
        ("browser.nudges", ObservationForm.SUMMARY, True, False),
        ("other", ObservationForm.FULL, True, False),
        ("browser.nudges", ObservationForm.FULL, False, False),
    ],
)
async def test_hint_acknowledgement_requires_matching_full_provenance(
    source, form, matching_ref, delivered
):
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
                ModelRequest(model="test", messages=(User(nudge_id),)), request_id="request"
            )
        )
        assert (await nudges.project(_snapshot())).refs == (nudge_id,)
        included = ObservationsIncludedEvent(
            request_id="request",
            observations=(
                IncludedObservation(source, (nudge_id if matching_ref else "unknown",), form),
            ),
        )
        await session.emit(included)
        await session.emit(included)
        receipts = [event for event in session.events if isinstance(event, NudgeIncludedEvent)]
        assert len(receipts) == int(delivered)
        assert (await nudges.project(_snapshot())).refs == (() if delivered else (nudge_id,))
        if delivered:
            assert receipts[0].request_id == "request"


async def test_hint_provenance_and_unselected_hints_survive_session_replay(tmp_path):
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
            JsonlSessions(tmp_path),
        ],
    )
    async with agent.session("hints") as session:
        nudges = holder["nudges"]
        await nudges.queue("First hint", key="first", cause_id="first-action")
        await nudges.queue("Second hint", key="second", cause_id="second-action")
        await session.run("Inspect")
        request = next(event for event in session.events if isinstance(event, ModelRequestedEvent))
        provenance = session.log.included_observations(request.request)
        (receipt,) = [event for event in session.events if isinstance(event, NudgeIncludedEvent)]
        assert receipt.request_id == request.request_id
        assert provenance == (
            IncludedObservation("browser.nudges", receipt.nudge_ids, ObservationForm.FULL),
        )
        assert "Second hint" in (await nudges.project(_snapshot())).full
    async with agent.session("hints") as restored:
        assert restored.log.included_observations(request.request) == provenance
        remaining = await holder["nudges"].project(_snapshot())
        assert "Second hint" in remaining.full
        assert "First hint" not in remaining.full


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
