"""Route the final-answer contract through done for sessions that mount Done.

Harnessed 0.13 has no output-policy hook or injectable output handler, so this
patches OutputHandler and dispatches by session log. Other sessions, including
concurrent ones, keep the native handler.
"""

import json
from collections.abc import Callable
from dataclasses import replace

from harnessed import SessionLog, ToolResult
from harnessed.core.messages import to_dict
from harnessed.core.model import OutputSchema
from harnessed.core.runtime.output import OutputHandler
from harnessed.models import AssistantMessage, Model, ModelRequest, SystemMessage

Finished = Callable[[], bool]

# Retain native methods once; each activation owns exactly one registry entry.
_NATIVE_PREPARE = OutputHandler.prepare
_NATIVE_VALIDATE = OutputHandler.validate
_ACTIVE: dict[SessionLog, Finished] = {}


def activate(log: SessionLog, finished: Finished) -> Callable[[], None]:
    """Hold the final-answer contract back until finished() and return the undo."""
    _ACTIVE[log] = finished
    OutputHandler.prepare = _prepare
    OutputHandler.validate = _validate

    def restore() -> None:
        _ACTIVE.pop(log, None)
        if not _ACTIVE:
            if OutputHandler.prepare is _prepare:
                OutputHandler.prepare = _NATIVE_PREPARE
            if OutputHandler.validate is _validate:
                OutputHandler.validate = _NATIVE_VALIDATE

    return restore


def _prepare(
    self: OutputHandler,
    request: ModelRequest,
    schema: OutputSchema | None,
    *,
    model: Model,
) -> ModelRequest:
    finished = _ACTIVE.get(self.log)
    # Once finished, tools stay declared to keep the cached prefix; the phase gate
    # blocks them, and done's result already carries the final-answer instruction.
    if finished is None or finished():
        return _NATIVE_PREPARE(self, request, schema, model=model)
    if schema is not None:
        instruction = (
            "After done, the final answer must match this JSON Schema. "
            "Progress messages before done may use ordinary text.\n"
            + json.dumps(to_dict(schema.json_schema), ensure_ascii=False)
        )
        request = replace(
            request, messages=(*request.messages, SystemMessage(instruction))
        )
    return replace(request, output_schema=None)


async def _validate(
    self: OutputHandler, response: AssistantMessage, schema: OutputSchema | None
) -> tuple[dict[str, ToolResult], str | None]:
    finished = _ACTIVE.get(self.log)
    if finished is None or finished():
        return await _NATIVE_VALIDATE(self, response, schema)
    return {}, None
