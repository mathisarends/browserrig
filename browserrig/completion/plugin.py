import json

from harnessed import Plugin, SystemPrompt, tool
from harnessed.events import AssistantMessageEvent, ToolCallFinishedEvent
from harnessed.hooks import (
    ExecuteTool,
    Next,
    OutputDecision,
    PrepareOutput,
    PrepareRequest,
    PreStep,
    StepDecision,
    ToolPolicy,
    TurnStopping,
)
from harnessed.kernel import PluginState, hook, needs
from harnessed.models import (
    Decision,
    ModelRequest,
    StopReason,
    SystemMessage,
    ToolResult,
    ToolStatus,
    UserMessage,
)
from harnessed.prompts import Instructions
from harnessed.sessions import SessionContext
from harnessed.tools import ToolChain, tool_name

from .models import DENIALS, Phase, closing_step, permits
from .state import CompletionState

_FINAL_INSTRUCTION = (
    "Browser work has ended. Write the final answer now, using the results already "
    "available. Follow the output format requested in the task and any declared output "
    "schema. Do not add commentary outside that format. Report uncertainties and "
    "unfinished work honestly. Application tools are no longer available."
)

_CLOSING_HINT = (
    "Step {step} of {max_steps}: this is the last step that still leaves room for a "
    "final answer. Call {tool} alone now, with success=false if the task is unfinished. "
    "Other tools are blocked from here on."
)

_INSTRUCTIONS = (
    "Brief progress messages between tool calls do not end the task. When browser "
    "work is finished, inspect the last action's result, then call {tool} alone. Write "
    "the final answer in the next response, following the requested format and any "
    "declared output schema. Use success=false if the task could not be completed. "
    "Do not call {tool} before required work is finished."
)


class Done(Plugin, slot="completion", provides=True):
    """Require done() before the final answer; ordinary text remains commentary.

    Mount with plugins=[Done()]. The final response uses the run's native output
    contract, if any. Both phases count toward the existing step/token budgets.
    On the last step that still leaves room for a final answer, the model is told to
    call done and every other tool is blocked. Tool definitions never change between
    phases, so the cached prompt prefix stays valid.
    """

    _session = needs(SessionContext)
    _state = PluginState(CompletionState)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Explicit task completion",
                text=_INSTRUCTIONS.format(tool=tool_name(self.done)),
            )
        )

    @property
    def remaining_work_steps(self) -> int:
        """Count steps through the last step where browser work can continue."""
        closing = self._state.closing_step
        if closing is None or self._finished():
            return 0
        return max(0, closing - self._state.step)

    @hook(PrepareRequest)
    async def _output_guidance(
        self, event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        if event.session.log is not self._session.log or self._finished():
            return request
        schema = event.session.log.current_turn().start.output_schema
        if schema is None:
            return request
        name = tool_name(self.done)
        return request.append_message(
            SystemMessage(
                f"After {name}, the final answer must match this JSON Schema. "
                f"Progress messages before {name} may use ordinary text.\n"
                + json.dumps(schema.json_schema, default=dict, ensure_ascii=False)
            )
        )

    @hook(PrepareOutput)
    async def _prepare_output(
        self, event: PrepareOutput, next_: Next[OutputDecision]
    ) -> OutputDecision:
        decision = await next_()
        if event.session.log is self._session.log and not self._finished():
            return OutputDecision.DEFER
        return decision

    @tool(
        description="End browser work and enter final-answer mode.",
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
        if event.session.log is not self._session.log or self._finished():
            return None
        answer = event.session.log.last(AssistantMessageEvent)
        if answer is not None and answer.stop_reason in (
            StopReason.CONTENT_FILTER,
            StopReason.ERROR,
            StopReason.MAX_TOKENS,
        ):
            return None
        return True

    @hook(PreStep)
    async def _before_step(
        self, event: PreStep, next_: Next[StepDecision]
    ) -> StepDecision:
        decision = await next_()
        if event.session.log is not self._session.log or not decision.accepted:
            return decision
        progress = event.progress
        state = self._state
        state.step = progress.step
        state.closing_step = closing_step(progress.last_tool_step)
        if progress.step == state.closing_step and not self._finished():
            # Observed after the page observation so the hint is the latest context.
            event.session.observe(
                UserMessage(
                    content=_CLOSING_HINT.format(
                        step=progress.step,
                        max_steps=progress.max_steps,
                        tool=tool_name(self.done),
                    )
                ),
                source="completion",
            )
        return decision

    @hook(ToolPolicy, priority=-200)
    async def _phase_policy(self, event: ToolPolicy, next_: Next[Decision]) -> Decision:
        # Refuse calls the phase forbids before ordinary approval hooks can ask
        # the host to authorize work that is no longer permitted.
        if event.session.log is self._session.log and not permits(
            self._phase(), is_done=event.matches(self.done)
        ):
            return Decision.DENY
        return await next_()

    @hook(ExecuteTool, priority=-100)
    async def _guard(self, event: ExecuteTool, next_: Next[ToolResult]) -> ToolResult:
        if event.session.log is not self._session.log:
            return await next_()
        phase = self._phase()
        name = tool_name(self.done)
        if not permits(phase, is_done=event.matches(self.done)):
            return ToolResult(
                DENIALS[phase].format(tool=name), ToolStatus.ERROR, break_chain=True
            )
        answer = event.session.log.last(AssistantMessageEvent)
        calls = answer.message.tool_calls if answer is not None else ()
        if len(calls) > 1 and any(call.name == name for call in calls):
            return ToolResult(
                f"Call {name} alone, after inspecting the last action's result.",
                ToolStatus.ERROR,
                break_chain=True,
            )
        return await next_()

    def _phase(self) -> Phase:
        if self._finished():
            return Phase.FINISHED
        closing = self._state.closing_step
        if closing is not None and self._state.step >= closing:
            return Phase.CLOSING
        return Phase.WORKING

    def _finished(self) -> bool:
        turn = self._session.log.open_turn
        name = tool_name(self.done)
        return turn is not None and any(
            isinstance(event, ToolCallFinishedEvent)
            and event.call.name == name
            and event.result.status is ToolStatus.OK
            for event in turn.events
        )
