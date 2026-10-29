import pytest
from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import Nudges
from browserrig.events import (
    ActionFinishedEvent,
    ActionStartedEvent,
    NudgeQueuedEvent,
    ObservationCapturedEvent,
)
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
                before_url="https://example.org/",
                after_url=after_url,
                before_document="doc-1",
                before_fingerprint="before",
                before_scroll_y=0,
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
                mode="web",
                readiness="ready",
            )
        )
        actual = any(
            isinstance(e, NudgeQueuedEvent) and e.key == "unexpected_scroll" for e in session.events
        )
        assert actual is expected
