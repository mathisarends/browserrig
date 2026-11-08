import json
import sys
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import TextIO

from harnessed import Plugin, ToolResult, hook
from harnessed.events import (
    ApprovalRequestedEvent,
    CompactionFinishedEvent,
    CompactionStartedEvent,
    ModelAttemptFinishedEvent,
    ModelAttemptStartedEvent,
    ModelRetryScheduledEvent,
    SessionEvent,
    ToolCallFinishedEvent,
    ToolCallRequestedEvent,
    ToolExecutionFinishedEvent,
)
from harnessed.hooks import SessionAppended

from .events import BrowserEvent, EventKind, LiveEvent

_METADATA = {
    "request_id",
    "call_id",
    "turn_id",
    "step_id",
    "message_id",
    "state",
    "status",
    "outcome",
    "reason",
    "duration",
    "elapsed",
    "step",
    "model",
    "dispatched",
    "compaction_id",
    "retry_group_id",
    "retry_kind",
    "attempt",
    "retry_count",
    "max_retries",
    "delay_seconds",
    "status_code",
    "partial",
    "max_steps",
    "final_step",
}

type _TerminalEvent = (
    SessionEvent
    | LiveEvent
    | CompactionStartedEvent
    | CompactionFinishedEvent
    | ModelAttemptStartedEvent
    | ModelRetryScheduledEvent
    | ModelAttemptFinishedEvent
)


class TerminalEvents(Plugin):
    def __init__(self, output: TextIO | None = None) -> None:
        super().__init__()
        self._output = output

    def _write(self, event: _TerminalEvent) -> None:
        print(
            json.dumps(_event_record(event), ensure_ascii=True, allow_nan=False),
            file=self._output if self._output is not None else sys.stderr,
            flush=True,
        )

    @hook(SessionAppended)
    def _appended(self, receipt: SessionAppended) -> None:
        self._write(receipt.event)

    @hook(
        LiveEvent,
        CompactionStartedEvent,
        CompactionFinishedEvent,
        ModelAttemptStartedEvent,
        ModelRetryScheduledEvent,
        ModelAttemptFinishedEvent,
    )
    def _transient(self, event: _TerminalEvent) -> None:
        self._write(event)


def _event_record(event: _TerminalEvent) -> dict[str, object]:
    if isinstance(event, BrowserEvent | LiveEvent):
        record = asdict(event)
        # Omit page/form contents. URLs and key names remain diagnostic metadata.
        for name in ("text", "message", "value", "preview", "image_url"):
            record.pop(name, None)
        if event.type is EventKind.WORK_PRESENTED:
            for name in ("title", "detail", "limitations"):
                record.pop(name, None)
        return record
    record: dict[str, object] = {"type": str(event.type)}
    for item in fields(event) if is_dataclass(event) else ():
        value = getattr(event, item.name)
        if item.name in _METADATA and (
            value is None or isinstance(value, str | int | float | bool | Enum)
        ):
            record[item.name] = value
    match event:
        case ApprovalRequestedEvent(call=call) | ToolCallRequestedEvent(call=call):
            record.update(tool=call.name, call_id=call.id)
        case ToolCallFinishedEvent(call=call, result=result):
            record.update(tool=call.name, call_id=call.id, **_result_record(result))
        case ToolExecutionFinishedEvent(result=result):
            record.update(_result_record(result))
    return record


def _result_record(result: ToolResult) -> dict[str, object]:
    return {
        "is_error": result.is_error,
        "tool_status": result.status,
        "break_chain": result.break_chain,
    }
