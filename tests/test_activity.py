from dataclasses import replace

import pytest
from harnessed import Agent, Context, Inject, Plugin, ToolResult
from harnessed.core.errors import SessionFormatError
from harnessed.events import EventRegistry, message, model, step, tool, turn
from harnessed.events import session as session_events
from harnessed.models import Assistant, ModelRequest
from harnessed.testing import ScriptedModel

from browserrig.activity import Activity, ActivityKind, ActivityOutcome
from browserrig.activity.models import ActivityKey, project_intervals
from browserrig.events import (
    ACTIVITY_EVENTS,
    READINESS_EVENTS,
    ActivityFinishedEvent,
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)
from browserrig.kinds import ObservationKind, ReadinessPhase


class _Access(Plugin, needs=(Activity,)):
    events = READINESS_EVENTS

    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, _ctx: Context, activity: Inject[Activity]):
        self.holder["activity"] = activity


@pytest.fixture(name="activity_session")
async def _activity_session():
    holder = {}
    agent = Agent(model=ScriptedModel(["ok"]), plugins=[Activity(), _Access(holder)])
    async with agent.session() as session:
        yield session, holder["activity"]


def _request():
    return model.Requested(request=ModelRequest(model="test", messages=()))


def _readiness_started(readiness_id):
    return ReadinessStartedEvent(
        readiness_id=readiness_id,
        mode=ObservationKind.DOM,
        phase=ReadinessPhase.ACTION,
    )


def _readiness_ended(kind, readiness_id, reason=""):
    return kind(
        readiness_id=readiness_id,
        mode=ObservationKind.DOM,
        phase=ReadinessPhase.ACTION,
        duration=0.1,
        reason=reason,
    )


async def test_readiness_ids_cannot_close_model_pause_or_tool_intervals(activity_session):
    session, activity = activity_session
    await session.emit(_request())
    await session.emit(_readiness_started("llm"))
    assert len(activity.intervals()) == 2
    assert all(item.outcome is ActivityOutcome.RUNNING for item in activity.intervals())
    await session.emit(session_events.ControlChanged(state=session_events.ControlState.PAUSED))
    await session.emit(_readiness_started("paused"))
    await session.emit(tool.ExecutionStarted(call_id="shared"))
    await session.emit(_readiness_started("tool:shared"))
    await session.emit(tool.ExecutionFinished(call_id="shared", result=ToolResult("ok")))

    intervals = activity.intervals()
    closed = [item for item in intervals if item.outcome is ActivityOutcome.COMPLETED]
    assert {item.kind for item in closed} == {ActivityKind.LLM, ActivityKind.TOOL}
    running = [item for item in intervals if item.outcome is ActivityOutcome.RUNNING]
    assert {item.cause_id for item in running if item.kind is ActivityKind.READINESS} == {
        "llm",
        "paused",
        "tool:shared",
    }
    assert any(item.kind is ActivityKind.PAUSED for item in running)
    assert not any(item.outcome is ActivityOutcome.SUPERSEDED for item in intervals)


async def test_replacing_an_interval_supersedes_only_the_same_correlated_activity(activity_session):
    session, activity = activity_session
    await session.emit(_readiness_started("first"))
    await session.emit(_readiness_started("second"))
    original = {item.cause_id: item.interval_id for item in activity.intervals()}
    await session.emit(_readiness_started("first"))
    replaced = next(
        item for item in activity.intervals() if item.outcome is ActivityOutcome.SUPERSEDED
    )
    assert replaced.interval_id == original["first"]
    live = [item for item in activity.intervals() if item.outcome is ActivityOutcome.RUNNING]
    assert len(live) == 2
    assert (
        next(item for item in live if item.cause_id == "second").interval_id == original["second"]
    )
    assert next(item for item in live if item.cause_id == "first").interval_id != original["first"]


@pytest.mark.parametrize(
    "event_type,expected",
    [
        (ReadyEvent, ActivityOutcome.COMPLETED),
        (ReadinessDegradedEvent, ActivityOutcome.DEGRADED),
        (ReadinessFailedEvent, ActivityOutcome.FAILED),
        (ReadinessCancelledEvent, ActivityOutcome.CANCELLED),
    ],
)
async def test_readiness_outcome_comes_from_event_type_and_preserves_reason(
    activity_session, event_type, expected
):
    session, activity = activity_session
    await session.emit(_readiness_started("probe"))
    # A reason that looks like a lifecycle value must still remain diagnostic text.
    ended = _readiness_ended(event_type, "probe", reason="superseded")
    await session.emit(ended)
    await session.emit(ended)
    intervals = activity.intervals()
    assert len(intervals) == 1
    assert intervals[0].outcome is expected
    assert intervals[0].reason == "superseded"


@pytest.mark.parametrize(
    "result,expected",
    [
        (ToolResult("ok"), ActivityOutcome.COMPLETED),
        (ToolResult.error("failure details"), ActivityOutcome.FAILED),
        (ToolResult.denied("denied details"), ActivityOutcome.FAILED),
        (ToolResult.unavailable("unavailable details"), ActivityOutcome.FAILED),
        (ToolResult("nonzero exit details", exit_code=1), ActivityOutcome.FAILED),
    ],
)
async def test_tool_receipt_closes_only_its_activity_and_retains_failure_status(
    activity_session, result, expected
):
    session, activity = activity_session
    await session.emit(tool.ExecutionStarted(call_id="first"))
    await session.emit(tool.ExecutionStarted(call_id="second"))
    await session.emit(tool.ExecutionFinished(call_id="first", result=result))
    intervals = {item.cause_id: item for item in activity.intervals()}
    assert intervals["first"].outcome is expected
    assert intervals["second"].outcome is ActivityOutcome.RUNNING
    assert bool(intervals["first"].reason) == result.is_error
    assert "details" not in intervals["first"].reason
    if result.exit_code == 1:
        assert "exit_code=1" in intervals["first"].reason


@pytest.mark.parametrize("reason", list(step.Outcome))
async def test_each_step_outcome_closes_model_wait_with_a_typed_outcome(activity_session, reason):
    session, activity = activity_session
    await session.emit(turn.Started(turn_id="turn"))
    await session.emit(step.Started(turn_id="turn", step=1))
    await session.emit(_request())
    await session.emit(step.Finished(turn_id="turn", step=1, reason=reason))
    (interval,) = activity.intervals()
    assert isinstance(interval.outcome, ActivityOutcome)
    assert interval.outcome.value == reason.value
    await session.emit(turn.Ended(turn_id="turn"))


@pytest.mark.parametrize("reason", list(turn.Outcome))
async def test_turn_end_closes_correlated_activities_but_keeps_pause_open(activity_session, reason):
    session, activity = activity_session
    await session.emit(turn.Started(turn_id="turn"))
    await session.emit(tool.ExecutionStarted(call_id="pending"))
    await session.emit(_readiness_started("probe"))
    await session.emit(session_events.ControlChanged(state=session_events.ControlState.PAUSED))
    await session.emit(turn.Ended(turn_id="turn", reason=reason))
    intervals = activity.intervals()
    closed = [item for item in intervals if item.kind is not ActivityKind.PAUSED]
    assert len(closed) == 2
    assert all(isinstance(item.outcome, ActivityOutcome) for item in closed)
    assert all(item.outcome.value == reason.value for item in closed)
    pause = next(item for item in intervals if item.kind is ActivityKind.PAUSED)
    assert pause.outcome is ActivityOutcome.RUNNING
    await session.emit(session_events.ControlChanged(state=session_events.ControlState.ACTIVE))
    assert all(item.outcome is not ActivityOutcome.RUNNING for item in activity.intervals())


async def test_assistant_interruption_and_teardown_emit_one_finish_per_interval():
    agent = Agent(model=ScriptedModel(["ok"]), plugins=[Activity(), _Access({})])
    async with agent.session() as session:
        await session.emit(_request())
        await session.emit(message.Assistant(message=Assistant("partial"), interrupted=True))
        await session.emit(_readiness_started("pending"))
    intervals = project_intervals(session.events)
    assert len(intervals) == 2
    assert {item.outcome for item in intervals} == {
        ActivityOutcome.INTERRUPTED,
        ActivityOutcome.CLOSED,
    }
    assert len({item.interval_id for item in intervals}) == len(intervals)


@pytest.mark.parametrize("outcome", list(ActivityOutcome))
def test_activity_outcomes_roundtrip_as_enums_with_separate_diagnostic_text(outcome):
    registry = EventRegistry(ACTIVITY_EVENTS)
    event = ActivityFinishedEvent(
        interval_id="interval",
        kind=ActivityKind.READINESS,
        cause_id="probe",
        started_at=1,
        at=2,
        outcome=outcome,
        reason="Canvas is still loading",
        epoch_id="epoch",
    )
    record = registry.encode(event)
    restored = registry.decode(record)
    assert restored == event
    assert restored.outcome is outcome
    assert restored.kind is ActivityKind.READINESS
    with pytest.raises(ValueError):
        replace(event, outcome="compleeted")
    record["data"]["outcome"] = "compleeted"
    with pytest.raises(SessionFormatError, match="payload"):
        registry.decode(record)


def test_existing_known_outcomes_load_without_the_new_reason_field():
    registry = EventRegistry(ACTIVITY_EVENTS)
    record = registry.encode(
        ActivityFinishedEvent(
            interval_id="existing",
            kind=ActivityKind.LLM,
            cause_id="request",
            started_at=1,
            at=2,
            outcome=ActivityOutcome.COMPLETED,
        )
    )
    del record["data"]["reason"]
    restored = registry.decode(record)
    assert restored.outcome is ActivityOutcome.COMPLETED
    assert restored.reason == ""


@pytest.mark.parametrize(
    "kind,correlation_id",
    [
        (ActivityKind.LLM, "unexpected"),
        (ActivityKind.PAUSED, "unexpected"),
        (ActivityKind.TOOL, ""),
        (ActivityKind.READINESS, ""),
    ],
)
def test_activity_keys_reject_invalid_singleton_or_correlated_combinations(kind, correlation_id):
    with pytest.raises(ValueError):
        ActivityKey(kind, correlation_id)
