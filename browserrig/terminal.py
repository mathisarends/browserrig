import json
import sys
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import TextIO

from harnessed import Plugin, hook
from harnessed.events import SessionEvent
from harnessed.hooks import SessionAppended

from .events import BrowserEvent, InputEvent

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
}


def _event_record(event: SessionEvent | InputEvent) -> dict[str, object]:
    if isinstance(event, BrowserEvent | InputEvent):
        record = asdict(event)
        # Nudges and page dialogs can contain arbitrary page text.
        for name in ("text", "message"):
            record.pop(name, None)
        return record
    record: dict[str, object] = {"type": str(event.type)}
    for item in fields(event) if is_dataclass(event) else ():
        value = getattr(event, item.name)
        if item.name in _METADATA and isinstance(value, str | int | float | bool | Enum):
            record[item.name] = value
    call = getattr(event, "call", None)
    if call is not None:
        record.update(tool=call.name, call_id=call.id)
    result = getattr(event, "result", None)
    if result is not None and hasattr(result, "is_error"):
        record["is_error"] = result.is_error
    return record


class TerminalEvents(Plugin):
    def __init__(self, output: TextIO | None = None) -> None:
        super().__init__()
        self._output = output

    def _write(self, event: SessionEvent | InputEvent) -> None:
        print(
            json.dumps(_event_record(event), ensure_ascii=True, allow_nan=False),
            file=self._output if self._output is not None else sys.stderr,
            flush=True,
        )

    @hook(SessionAppended)
    def _appended(self, receipt: SessionAppended) -> None:
        self._write(receipt.event)

    @hook(InputEvent)
    def _input_event(self, event: InputEvent) -> None:
        self._write(event)
