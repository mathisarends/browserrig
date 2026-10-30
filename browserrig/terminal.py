import json
import sys
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import TextIO

from harnessed import Plugin, hook
from harnessed.events import (
    CompactionFinishedEvent,
    CompactionStartedEvent,
    ModelAttemptFinishedEvent,
    ModelAttemptStartedEvent,
    ModelRetryScheduledEvent,
    SessionEvent,
)
from harnessed.hooks import SessionAppended

from .events import BrowserEvent, LiveEvent

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

    @hook(LiveEvent)
    def _live_event(self, event: LiveEvent) -> None:
        self._write(event)

    @hook(CompactionStartedEvent)
    def _compaction_started(self, event: CompactionStartedEvent) -> None:
        self._write(event)

    @hook(CompactionFinishedEvent)
    def _compaction_finished(self, event: CompactionFinishedEvent) -> None:
        self._write(event)

    @hook(ModelAttemptStartedEvent)
    def _attempt_started(self, event: ModelAttemptStartedEvent) -> None:
        self._write(event)

    @hook(ModelRetryScheduledEvent)
    def _retry_scheduled(self, event: ModelRetryScheduledEvent) -> None:
        self._write(event)

    @hook(ModelAttemptFinishedEvent)
    def _attempt_finished(self, event: ModelAttemptFinishedEvent) -> None:
        self._write(event)


def _event_record(event: _TerminalEvent) -> dict[str, object]:
    if isinstance(event, BrowserEvent | LiveEvent):
        record = asdict(event)
        # Omit page/form contents. URLs and key names remain diagnostic metadata.
        for name in ("text", "message", "value"):
            record.pop(name, None)
        return record
    record: dict[str, object] = {"type": str(event.type)}
    for item in fields(event) if is_dataclass(event) else ():
        value = getattr(event, item.name)
        if item.name in _METADATA and (
            value is None or isinstance(value, str | int | float | bool | Enum)
        ):
            record[item.name] = value
    call = getattr(event, "call", None)
    if call is not None:
        record.update(tool=call.name, call_id=call.id)
    result = getattr(event, "result", None)
    if result is not None and hasattr(result, "is_error"):
        record["is_error"] = result.is_error
        record["tool_status"] = result.status
        record["break_chain"] = result.break_chain
    return record
