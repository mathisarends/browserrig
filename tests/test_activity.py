from dataclasses import replace

import pytest
from harnessed import Agent, Context, Inject, Plugin, ToolResult, ToolStatus
from harnessed.core.errors import SessionFormatError
from harnessed.events import (
    AgentControlChangedEvent,
    AssistantMessageEvent,
    ControlState,
    EventRegistry,
    ModelRequestedEvent,
    ModelRequestFailedEvent,
    ModelRequestOutcome,
    StepEndedEvent,
    StepOutcome,
    StepStartedEvent,
    ToolExecutionFinishedEvent,
    ToolExecutionStartedEvent,
    TurnEndedEvent,
    TurnOutcome,
    TurnStartedEvent,
)
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


class _Access(Plugin):
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


def _request(request_id="request"):
    return ModelRequestedEvent(
        request=ModelRequest(model="test", messages=()), request_id=request_id
    )


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
    await session.emit(AssistantMessageEvent(Assistant("ok"), request_id="request"))
    await session.emit(AgentControlChangedEvent(state=ControlState.PAUSED))
    await session.emit(_readiness_started("paused"))
    await session.emit(ToolExecutionStartedEvent(call_id="shared"))
    await session.emit(_readiness_started("tool:shared"))
    await session.emit(ToolExecutionFinishedEvent(call_id="shared", result=ToolResult("ok")))

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
        (ToolResult("cancelled details", status=ToolStatus.CANCELLED), ActivityOutcome.CANCELLED),
        (ToolResult("timeout details", status=ToolStatus.TIMEOUT), ActivityOutcome.TIMEOUT),
        (ToolResult("nonzero exit details", exit_code=1), ActivityOutcome.FAILED),
    ],
)
async def test_tool_receipt_closes_only_its_activity_and_retains_failure_status(
    activity_session, result, expected
):
    session, activity = activity_session
    await session.emit(ToolExecutionStartedEvent(call_id="first"))
    await session.emit(ToolExecutionStartedEvent(call_id="second"))
    await session.emit(ToolExecutionFinishedEvent(call_id="first", result=result))
    intervals = {item.cause_id: item for item in activity.intervals()}
    assert intervals["first"].outcome is expected
    assert intervals["second"].outcome is ActivityOutcome.RUNNING
    assert bool(intervals["first"].reason) == result.is_error
    assert "details" not in intervals["first"].reason
    if result.exit_code == 1:
        assert "exit_code=1" in intervals["first"].reason


@pytest.mark.parametrize("reason", list(StepOutcome))
async def test_each_step_outcome_closes_model_wait_with_a_typed_outcome(activity_session, reason):
    session, activity = activity_session
    await session.emit(TurnStartedEvent(turn_id="turn"))
    await session.emit(StepStartedEvent(turn_id="turn", step=1))
    await session.emit(_request())
    await session.emit(StepEndedEvent(turn_id="turn", step=1, reason=reason))
    (interval,) = activity.intervals()
    assert isinstance(interval.outcome, ActivityOutcome)
    assert interval.outcome.value == reason.value
    await session.emit(TurnEndedEvent(turn_id="turn"))


@pytest.mark.parametrize("reason", list(TurnOutcome))
async def test_turn_end_closes_correlated_activities_but_keeps_pause_open(activity_session, reason):
    session, activity = activity_session
    await session.emit(TurnStartedEvent(turn_id="turn"))
    await session.emit(ToolExecutionStartedEvent(call_id="pending"))
    await session.emit(_readiness_started("probe"))
    await session.emit(AgentControlChangedEvent(state=ControlState.PAUSED))
    await session.emit(TurnEndedEvent(turn_id="turn", reason=reason))
    intervals = activity.intervals()
    closed = [item for item in intervals if item.kind is not ActivityKind.PAUSED]
    assert len(closed) == 2
    assert all(isinstance(item.outcome, ActivityOutcome) for item in closed)
    assert all(item.outcome.value == reason.value for item in closed)
    pause = next(item for item in intervals if item.kind is ActivityKind.PAUSED)
    assert pause.outcome is ActivityOutcome.RUNNING
    await session.emit(AgentControlChangedEvent(state=ControlState.ACTIVE))
    assert all(item.outcome is not ActivityOutcome.RUNNING for item in activity.intervals())


async def test_assistant_interruption_and_teardown_emit_one_finish_per_interval():
    agent = Agent(model=ScriptedModel(["ok"]), plugins=[Activity(), _Access({})])
    async with agent.session() as session:
        await session.emit(_request())
        await session.emit(
            AssistantMessageEvent(
                message=Assistant("partial"), request_id="request", interrupted=True
            )
        )
        await session.emit(_readiness_started("pending"))
    intervals = project_intervals(session.events)
    assert len(intervals) == 2
    assert {item.outcome for item in intervals} == {
        ActivityOutcome.INTERRUPTED,
        ActivityOutcome.CLOSED,
    }
    assert len({item.interval_id for item in intervals}) == len(intervals)


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (ModelRequestOutcome.FAILED, ActivityOutcome.FAILED),
        (ModelRequestOutcome.CANCELLED, ActivityOutcome.CANCELLED),
        (ModelRequestOutcome.CONTEXT_EXCEEDED, ActivityOutcome.CONTEXT_LIMIT),
    ],
)
async def test_model_failure_closes_only_the_matching_request(activity_session, outcome, expected):
    session, activity = activity_session
    await session.emit(_request("first"))
    await session.emit(_request("retry"))
    failure = ModelRequestFailedEvent("first", outcome, reason="private provider details")
    await session.emit(failure)
    await session.emit(failure)
    intervals = {item.cause_id: item for item in activity.intervals()}
    assert len(intervals) == 2
    assert intervals["first"].outcome is expected
    assert intervals["first"].reason == outcome.value
    assert intervals["retry"].outcome is ActivityOutcome.RUNNING
    await session.emit(AssistantMessageEvent(Assistant("ok"), request_id="retry"))
    assert all(item.outcome is not ActivityOutcome.RUNNING for item in activity.intervals())


async def test_late_assistant_reply_cannot_close_another_model_request(activity_session):
    session, activity = activity_session
    await session.emit(_request("current"))
    await session.emit(AssistantMessageEvent(Assistant("old reply"), request_id="previous"))
    (interval,) = activity.intervals()
    assert interval.cause_id == "current"
    assert interval.outcome is ActivityOutcome.RUNNING


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
        (ActivityKind.LLM, ""),
        (ActivityKind.PAUSED, "unexpected"),
        (ActivityKind.TOOL, ""),
        (ActivityKind.READINESS, ""),
    ],
)
def test_activity_keys_reject_invalid_singleton_or_correlated_combinations(kind, correlation_id):
    with pytest.raises(ValueError):
        ActivityKey(kind, correlation_id)
