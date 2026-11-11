import pytest
from harnessed import Agent
from harnessed.events import IncludedObservation, ObservationsIncludedEvent
from harnessed.models import UserMessage
from harnessed.testing import ScriptedModel

from browserrig.observation import (
    DomRenderer,
    ElementInfo,
    ProjectObservation,
    Snapshot,
    TextContext,
)
from tests.fakes import FakeServices


@pytest.mark.parametrize("mode,repeat", [("delta", False), ("full", True)])
async def test_unchanged_observation_delivery_is_an_explicit_context_policy(
    mode, repeat
):
    services = FakeServices()
    agent = Agent(model=ScriptedModel([]), plugins=[services, TextContext(mode=mode)])
    async with agent.session() as session:
        services = _services(session)
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
    services = FakeServices()
    agent = Agent(model=ScriptedModel([]), plugins=[services, TextContext()])
    async with agent.session() as session:
        services = _services(session)
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
            services.observe.generation += 1
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


def _services(session):
    services = session.scope[FakeServices]
    services.observe.generation = 0
    services.observe.project = lambda snapshot: UserMessage(
        DomRenderer().render(snapshot)
    )
    return services


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
