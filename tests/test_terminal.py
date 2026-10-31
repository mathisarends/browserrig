import io
import json
from dataclasses import dataclass

from harnessed import (
    Agent,
    Inject,
    Plugin,
    SessionLog,
    ToolCall,
    ToolResult,
    ToolStatus,
    hook,
)
from harnessed.events import (
    CompactionFinishedEvent,
    CompactionStartedEvent,
    ModelAttemptFinishedEvent,
    ModelAttemptStartedEvent,
    ModelRequestedEvent,
    ModelRetryScheduledEvent,
    ToolCallFinishedEvent,
)
from harnessed.testing import ScriptedModel

from browserrig import TerminalEvents
from browserrig.events import INPUT_EVENTS, BrowserEvent, KeyPressedEvent, WaitingEvent
from browserrig.terminal import _event_record


async def test_terminal_observes_native_and_live_events_without_model_or_log_pollution():
    class Choreography(Plugin, needs=(SessionLog,)):
        events = INPUT_EVENTS

        @hook(ModelRequestedEvent)
        async def input(self, _event: ModelRequestedEvent, log: Inject[SessionLog]):
            await log.emit(KeyPressedEvent(key="x", action_id="action-1"))
            await log.emit(
                WaitingEvent(duration=2, browser_id="browser-1", target_id="tab-1")
            )

    output = io.StringIO()
    model = ScriptedModel(["Final answer"])
    agent = Agent(model=model, plugins=[TerminalEvents(output), Choreography()])
    async with agent.session() as session:
        result = await session.run("PRIVATE PROMPT")
        assert result.text == "Final answer"
        assert not any(isinstance(event, KeyPressedEvent) for event in result.events)
        assert not any(isinstance(event, WaitingEvent) for event in result.events)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    key = next(record for record in records if record["type"] == "browser.key.pressed")
    assert key["key"] == "x" and key["action_id"] == "action-1"
    wait = next(record for record in records if record["type"] == "browser.waiting")
    assert wait["duration"] == 2 and wait["target_id"] == "tab-1"
    assert wait["browser_id"] == "browser-1"
    assert any(
        record["type"] == ModelRequestedEvent.__dataclass_fields__["type"].default
        for record in records
    )
    assert "PRIVATE PROMPT" not in output.getvalue()
    assert "Final answer" not in output.getvalue()


def test_terminal_omits_arbitrary_page_and_form_value_fields():
    @dataclass(frozen=True)
    class FormEvent(BrowserEvent):
        value: str
        message: str
        text: str
        type: str = "test.form"

    record = _event_record(
        FormEvent(value="private form", message="page dialog", text="page text")
    )
    assert not {"text", "message", "value"} & record.keys()


async def test_terminal_reports_correlated_compaction_and_attempts_without_inventing_counters():
    output = io.StringIO()
    agent = Agent(model=ScriptedModel(["ok"]), plugins=[TerminalEvents(output)])
    events = (
        CompactionStartedEvent("compact-1"),
        ModelAttemptStartedEvent(request_id="request-1", retry_group_id="group-1"),
        ModelRetryScheduledEvent(
            request_id="request-1",
            retry_group_id="group-1",
            attempt=1,
            reason="rate_limit",
            delay_seconds=0.1,
        ),
        ModelAttemptFinishedEvent(
            request_id="request-1",
            retry_group_id="group-1",
            outcome="retrying",
        ),
        CompactionFinishedEvent("compact-1", "discarded"),
    )
    async with agent.session() as session:
        for event in events:
            await session.emit(event)
        assert not any(
            isinstance(item, type(event)) for item in session.events for event in events
        )
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    activity = [r for r in records if r.get("compaction_id") or r.get("retry_group_id")]
    assert len(activity) == len(events)
    assert activity[0]["compaction_id"] == activity[-1]["compaction_id"] == "compact-1"
    assert activity[1]["attempt"] is None and activity[1]["retry_count"] is None
    assert activity[2]["retry_kind"] == "provider" and activity[2]["attempt"] == 1
    assert (
        activity[3]["outcome"] == "retrying" and activity[-1]["outcome"] == "discarded"
    )


def test_terminal_distinguishes_skipped_calls_and_chain_breaks_without_result_contents():
    result = ToolResult("PRIVATE RESULT", status=ToolStatus.SKIPPED, break_chain=True)
    record = _event_record(ToolCallFinishedEvent(ToolCall("click", {}), result))
    assert record["tool_status"] == "skipped" and record["break_chain"] is True
    assert "PRIVATE RESULT" not in str(record)
