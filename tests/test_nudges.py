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

from browserrig import Browser, Nudges
from browserrig.events import (
    ActionFinishedEvent,
    ActionStartedEvent,
    NudgeIncludedEvent,
    NudgeQueuedEvent,
    ObservationCapturedEvent,
    PageState,
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
        nudges, browser = holder["nudges"], holder["browser"]
        await nudges.queue(browser, "Inspect the page", key="hint", cause_id="action")
        observation = await nudges.project(_snapshot(), browser)
        (nudge_id,) = observation.refs
        # Text coincidence cannot acknowledge delivery, even in a submitted request.
        await session.emit(
            ModelRequestedEvent(
                ModelRequest(model="test", messages=(User(nudge_id),)), request_id="request"
            )
        )
        assert (await nudges.project(_snapshot(), browser)).refs == (nudge_id,)
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
        assert (await nudges.project(_snapshot(), browser)).refs == (
            () if delivered else (nudge_id,)
        )
        if delivered:
            assert receipts[0].request_id == "request"


async def test_hint_provenance_and_unselected_hints_survive_session_replay(tmp_path):
    holder = {}

    class Hints(Plugin, needs=(Nudges, Browser)):
        @hook(PreStep)
        async def observe_hints(
            self,
            event: PreStep,
            next_: Next[StepDecision],
            nudges: Inject[Nudges],
            browser: Inject[Browser],
        ) -> StepDecision:
            event.session.observe(await nudges.project(_snapshot(), browser))
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
        nudges, browser = holder["nudges"], holder["browser"]
        await nudges.queue(browser, "First hint", key="first", cause_id="first-action")
        await nudges.queue(browser, "Second hint", key="second", cause_id="second-action")
        await session.run("Inspect")
        request = next(event for event in session.events if isinstance(event, ModelRequestedEvent))
        provenance = session.log.included_observations(request.request)
        (receipt,) = [event for event in session.events if isinstance(event, NudgeIncludedEvent)]
        assert receipt.request_id == request.request_id
        assert provenance == (
            IncludedObservation("browser.nudges", receipt.nudge_ids, ObservationForm.FULL),
        )
        assert "Second hint" in (await nudges.project(_snapshot(), browser)).full
    async with agent.session("hints") as restored:
        assert restored.log.included_observations(request.request) == provenance
        remaining = await holder["nudges"].project(_snapshot(), holder["browser"])
        assert "Second hint" in remaining.full
        assert "First hint" not in remaining.full
