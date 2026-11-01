"""Explicit completion with free-form progress and a separate final response."""

import json
from dataclasses import replace

from harnessed import (
    Context,
    Instructions,
    Plugin,
    PolicyDecision,
    Session,
    ToolChain,
    ToolResult,
    ToolStatus,
    hook,
    tool,
)
from harnessed.core.messages import to_dict
from harnessed.core.model import OutputSchema
from harnessed.core.runtime.output import OutputHandler
from harnessed.events import AssistantMessageEvent, ToolCallFinishedEvent
from harnessed.hooks import ExecuteTool, Next, ToolPolicy, TurnStopping
from harnessed.kernel import dependency
from harnessed.models import (
    AssistantMessage,
    Model,
    ModelRequest,
    StopReason,
    SystemMessage,
)

_FINAL_INSTRUCTION = (
    "Browser work has ended. Write the final answer now, using the results already "
    "available. Follow the output format requested in the task and any declared output "
    "schema. Do not add commentary outside that format. Report uncertainties and "
    "unfinished work honestly. Application tools are no longer available."
)


class Done(Plugin, slot="completion"):
    """Require done() before the final answer; ordinary text remains commentary.

    Mount with plugins=[Done()]. The final response uses the run's native output
    contract, if any. Both phases count toward the existing step/token budgets.
    """

    _session = dependency(Session)

    usage = Instructions(
        title="Explicit task completion",
        text=(
            "You may write brief progress messages between tool calls, including "
            "standalone text messages. These do not end the task. When browser work "
            "is finished, call done alone, after inspecting the last action's result. "
            "Then write the final answer in the next response, following the format "
            "requested by the user and any declared output schema. Use success=false "
            "if the task could not be completed. A success report is your assessment, "
            "not independent verification. Do not call done before required work is finished."
        ),
    )

    async def setup(self, ctx: Context) -> None:
        # Harnessed 0.9.0 has no output-policy hook. Isolate the per-session bridge
        # here; requests, validation, retries, streaming and limits remain native.
        # pylint: disable=protected-access
        steps = self._session._steps
        previous = steps.outputs
        current = _CompletionOutput(previous, self)
        steps.outputs = current

        def restore() -> None:
            if steps.outputs is current:
                steps.outputs = previous

        ctx.effect(restore)

    @tool(
        description=(
            "End browser work and move to the final answer. Call this tool alone, "
            "after checking the last action's result. The next response must give the "
            "final answer in the requested format, without further application tools. "
            "Set success=false when the requested task could not be completed."
        ),
        readonly=True,
        chain=ToolChain.STOP_AFTER,
    )
    async def done(self, success: bool) -> str:
        return (
            f"Browser work ended; agent-reported success={str(success).lower()}. "
            + _FINAL_INSTRUCTION
        )

    @hook(TurnStopping)
    def _continue(self, event: TurnStopping) -> bool | None:
        if event.session is not self._session or self._finished():
            return None
        answer = event.session.log.last(AssistantMessageEvent)
        if answer is not None and answer.stop_reason in (
            StopReason.CONTENT_FILTER,
            StopReason.ERROR,
            StopReason.MAX_TOKENS,
        ):
            return None
        return True

    @hook(ToolPolicy, priority=-200)
    async def _final_policy(
        self, event: ToolPolicy, next_: Next[PolicyDecision]
    ) -> PolicyDecision:
        # Refuse hallucinated application calls before ordinary approval hooks
        # can ask the host to authorize work that is no longer permitted.
        if event.session is self._session and self._finished():
            return PolicyDecision.DENY
        return await next_()

    @hook(ExecuteTool, priority=-100)
    async def _guard(self, event: ExecuteTool, next_: Next[ToolResult]) -> ToolResult:
        if event.session is not self._session:
            return await next_()
        if self._finished():
            return ToolResult(
                "Browser work has ended. Return the final answer without application tools.",
                ToolStatus.ERROR,
                break_chain=True,
            )
        answer = event.session.log.last(AssistantMessageEvent)
        calls = answer.message.tool_calls if answer is not None else ()
        if len(calls) > 1 and any(call.name == "done" for call in calls):
            return ToolResult(
                "Call done alone, after inspecting the last action's result.",
                ToolStatus.ERROR,
                break_chain=True,
            )
        return await next_()

    def _finished(self) -> bool:
        turn = self._session.log.open_turn
        return turn is not None and any(
            isinstance(event, ToolCallFinishedEvent)
            and event.call.name == "done"
            and event.result.status is ToolStatus.OK
            for event in turn.events
        )


class _CompletionOutput(OutputHandler):
    def __init__(self, original: OutputHandler, completion: Done) -> None:
        super().__init__(original.ctx, original.log, original.options, original.values)
        self.completion = completion

    def prepare(
        self, request: ModelRequest, schema: OutputSchema | None, *, model: Model
    ) -> ModelRequest:
        # pylint: disable=protected-access
        if self.completion._finished():
            request = replace(
                request,
                tools=(),
                messages=(*request.messages, SystemMessage(_FINAL_INSTRUCTION)),
            )
            return super().prepare(request, schema, model=model)
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

    async def validate(
        self, response: AssistantMessage, schema: OutputSchema | None
    ) -> tuple[dict[str, ToolResult], str | None]:
        # pylint: disable=protected-access
        if not self.completion._finished():
            return {}, None
        return await super().validate(response, schema)
