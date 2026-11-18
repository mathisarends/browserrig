import pytest
from harnessed import Agent
from harnessed.events import IncludedObservation, ObservationsIncludedEvent
from harnessed.testing import ScriptedModel

from browserrig import PageReadiness
from browserrig.observation import (
    BrowserPerception,
    DomText,
    DomTextMode,
    ElementInfo,
    ProjectObservation,
    Snapshot,
)
from tests.fakes import FakeChrome


@pytest.mark.parametrize("mode,repeat", [("delta", False), (DomTextMode.FULL, True)])
async def test_unchanged_observation_delivery_is_an_explicit_context_policy(
    mode, repeat
):
    agent = _agent(mode)
    async with agent.session() as session:
        snapshot = _snapshot()
        first = await session.scope.dispatch(
            ProjectObservation(snapshot), default=_empty
        )
        assert first is not None and '"Continue"' in first.text
        await session.scope.dispatch(_included(snapshot, first))
        marked = snapshot.model_copy(
            update={
                "id": "second",
                "elements": (snapshot.elements[0].model_copy(update={"new": True}),),
            }
        )
        again = await session.scope.dispatch(ProjectObservation(marked), default=_empty)
        assert (again is not None) is repeat
        changed = marked.model_copy(
            update={
                "id": "third",
                "elements": (marked.elements[0].model_copy(update={"name": "Finish"}),),
            }
        )
        message = await session.scope.dispatch(
            ProjectObservation(changed), default=_empty
        )
        assert message is not None and '"Finish"' in message.text


@pytest.mark.parametrize("invalidate", ["context", "backend", "viewport"])
async def test_a_lost_base_or_changed_geometry_requires_a_complete_observation(
    invalidate,
):
    agent = _agent()
    async with agent.session() as session:
        snapshot = _snapshot()
        first = await session.scope.dispatch(
            ProjectObservation(snapshot), default=_empty
        )
        await session.scope.dispatch(_included(snapshot, first))
        if invalidate == "context":
            await session.scope.dispatch(
                ObservationsIncludedEvent(request_id="compacted", observations=())
            )
        elif invalidate == "backend":
            session.scope[BrowserPerception].invalidate()
        else:
            snapshot = snapshot.model_copy(
                update={"viewport_revision": 1, "width": 900}
            )
        snapshot = snapshot.model_copy(update={"id": "fresh"})
        message = await session.scope.dispatch(
            ProjectObservation(snapshot), default=_empty
        )
        assert message is not None and message.text.startswith("# Example")
        assert '"Continue"' in message.text


def _agent(mode=DomTextMode.DELTA):
    return Agent(
        model=ScriptedModel([]),
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            BrowserPerception(text=DomText(mode=mode)),
        ],
    )


def _snapshot():
    return Snapshot(
        id="first",
        tab_id="tab-1",
        document_id="doc-1",
        url="https://example.org",
        title="Example",
        readiness="ready",
        width=800,
        height=600,
        scroll_y=0,
        fingerprint="page",
        elements=(ElementInfo(ref="button", role="button", name="Continue"),),
    )


def _included(snapshot, message):
    return ObservationsIncludedEvent(
        request_id="request",
        observations=(
            IncludedObservation(
                source="browser",
                refs=(snapshot.id,),
                turn_id="turn",
                step=1,
                message_id=message.id,
            ),
        ),
    )


async def _empty():
    return None
