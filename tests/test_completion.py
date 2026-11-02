import json
from dataclasses import replace

import pytest
from harnessed import (
    Agent,
    Plugin,
    PluginOrder,
    PolicyDecision,
    SectionDelivery,
    StopReason,
    SystemPrompt,
    ToolStatus,
    tool,
)
from harnessed.errors import OutputUnavailable, OutputValidationError
from harnessed.events import (
    ApprovalRequestedEvent,
    AssistantMessageEvent,
    OutputValidatedEvent,
    TextDeltaEvent,
    TurnFinishedEvent,
)
from harnessed.models import ModelChunk, ModelInfo, ModelUsage
from harnessed.plugins import AgentLoop, Approvals, FinalStepPolicy
from harnessed.testing import ScriptedModel, call
from pydantic import BaseModel, Field

import browserrig
from browserrig import Done


class _Answer(BaseModel):
    title: str
    count: int = Field(ge=1)


class _Work(Plugin):
    def __init__(self, performed):
        super().__init__()
        self.performed = performed

    @tool(readonly=True)
    async def inspect(self) -> str:
        self.performed.append("inspect")
        return "Observed one item"

    @tool
    async def mutate(self) -> str:
        self.performed.append("mutate")
        return "Changed one item"


def _answer(native, **data):
    return json.dumps(data) if native else call("final_answer", **data)


async def test_unmounted_completion_keeps_the_native_text_termination():
    model = ScriptedModel(["Ordinary final answer", "Unused"])
    result = await Agent(model=model).run("Task")
    assert result.completed and result.text == "Ordinary final answer"
    assert len(model.requests) == 1
    assert not model.requests[0].tools


async def test_commentary_and_tools_stream_before_done_and_a_separate_final_answer():
    performed = []
    inspection = call("inspect")
    inspection = replace(
        inspection,
        message=replace(inspection.message, content="Now I will inspect the page."),
    )
    model = ScriptedModel(
        [
            "I will start with the page.",
            inspection,
            "I found one item.",
            call("done", success=True),
            "title,count\nItem,1",
        ]
    )
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), _Work(performed)],
    )
    async with agent.session() as session:
        events = [
            event
            async for event in session.stream("Return the result as CSV.", max_steps=5)
        ]
    assert performed == ["inspect"]
    assert [event.text for event in events if isinstance(event, TextDeltaEvent)] == [
        "I will start with the page.",
        "Now I will inspect the page.",
        "I found one item.",
        "title,count\nItem,1",
    ]
    result = events[-1].result
    assert isinstance(events[-1], TurnFinishedEvent)
    assert result.completed and result.text == "title,count\nItem,1"
    assert len(model.requests) == 5
    assert model.requests[-1].tools == ()
    assert "Return the result as CSV." in "\n".join(
        message.text for message in model.requests[-1].messages
    )
    assert [
        event.message.text
        for event in result.events
        if isinstance(event, AssistantMessageEvent)
    ] == [
        "I will start with the page.",
        "Now I will inspect the page.",
        "I found one item.",
        "",
        "title,count\nItem,1",
    ]


@pytest.mark.parametrize("native", [False, True])
async def test_structured_output_applies_only_to_the_final_response(native):
    model = ScriptedModel(
        [
            "I am collecting the requested fields.",
            call("inspect"),
            "All fields are available.",
            call("done", success=True),
            _answer(native, title="Item", count=1),
        ],
        info=ModelInfo("test", supports_structured_output=native),
    )
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), _Work([])],
    )
    result = await agent.run("Collect the item.", output=_Answer, max_steps=5)
    assert result.completed
    assert result.output == _Answer(title="Item", count=1)
    assert all(request.output_schema is None for request in model.requests[:-1])
    assert all(
        "final_answer" not in {tool.name for tool in request.tools}
        for request in model.requests[:-1]
    )
    final = model.requests[-1]
    assert final.output_schema is not None
    assert final.output_schema.mode == ("native" if native else "tool")
    assert [tool.name for tool in final.tools] == ([] if native else ["final_answer"])
    assert any(
        '"count"' in message.text and "JSON Schema" in message.text
        for message in model.requests[0].messages
    )
    assert any(isinstance(event, OutputValidatedEvent) for event in result.events)


@pytest.mark.parametrize("native", [False, True])
async def test_invalid_final_output_uses_native_validation_and_correction(native):
    model = ScriptedModel(
        [
            "Working.",
            call("done", success=True),
            _answer(native, title="Item", count=0),
            _answer(native, title="Item", count=1),
        ],
        info=ModelInfo("test", supports_structured_output=native),
    )
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done()],
    ).run("Task", output=_Answer)
    assert result.completed and result.output.count == 1
    assert len(model.requests) == 4
    assert all(
        {tool.name for tool in request.tools} <= {"final_answer"}
        for request in model.requests[-2:]
    )


async def test_invalid_final_output_still_obeys_the_native_retry_limit():
    model = ScriptedModel(
        [call("done", success=False), call("final_answer", title="Item", count=0)]
    )
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), AgentLoop(output_retries=0)],
    )
    with pytest.raises(OutputValidationError):
        await agent.run("Task", output=_Answer)
    assert len(model.requests) == 2


@pytest.mark.parametrize("success", [False, True])
async def test_reported_task_success_is_independent_of_turn_completion(success):
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=ScriptedModel([call("done", success=success), "Final report"]),
        plugins=[Done()],
    ).run("Task")
    assert result.completed
    ((completion, receipt),) = result.tool_calls
    assert completion.arguments["success"] is success
    assert receipt.status is ToolStatus.OK
    assert f"success={str(success).lower()}" in receipt.text


async def test_denied_done_does_not_enter_finalization():
    model = ScriptedModel([call("done", success=True), "Still working."])
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), Approvals(deny=["done"], default=PolicyDecision.ALLOW)],
    )
    result = await agent.run("Task", max_steps=2)
    assert not result.completed and result.stop_reason is StopReason.MAX_STEPS
    assert "done" in {tool.name for tool in model.requests[-1].tools}
    assert result.tool_calls[0][1].status is ToolStatus.DENIED


@pytest.mark.parametrize("first", [True, False])
async def test_done_must_be_alone_and_mixed_batches_do_not_execute_work(first):
    performed = []
    completion = call("done", success=True)
    inspection = call("inspect")
    calls = (*completion.message.tool_calls, *inspection.message.tool_calls)
    mixed = replace(
        completion,
        message=replace(completion.message, tool_calls=calls if first else calls[::-1]),
    )
    model = ScriptedModel([mixed, call("done", success=True), "Final"])
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), _Work(performed)],
    ).run("Task")
    assert not performed
    assert result.completed and result.text == "Final"
    assert [receipt.status for _, receipt in result.tool_calls] == [
        ToolStatus.ERROR,
        ToolStatus.SKIPPED,
        ToolStatus.OK,
    ]


async def test_application_tools_cannot_execute_after_done_even_if_model_calls_them():
    performed = []
    model = ScriptedModel([call("done", success=True), call("inspect"), "Final"])
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), _Work(performed)],
    ).run("Task")
    assert result.completed and result.text == "Final"
    assert not performed
    assert all(request.tools == () for request in model.requests[1:])
    assert result.tool_calls[-1][1].status is ToolStatus.DENIED


async def test_finalization_does_not_request_approval_for_hallucinated_actions():
    performed = []
    model = ScriptedModel([call("done", success=True), call("mutate"), "Final"])
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), _Work(performed)],
    ).run("Task")
    assert result.completed and not performed
    assert result.tool_calls[-1][1].status is ToolStatus.DENIED
    assert not any(isinstance(event, ApprovalRequestedEvent) for event in result.events)


@pytest.mark.parametrize("with_done", [False, True])
async def test_step_limits_do_not_claim_completion_or_invent_structured_output(
    with_done,
):
    model = ScriptedModel([call("done", success=True) if with_done else "Working."])
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done()],
    ).run("Task", output=_Answer, max_steps=1)
    assert not result.completed and result.stop_reason is StopReason.MAX_STEPS
    with pytest.raises(OutputUnavailable):
        _ = result.output
    assert len(model.requests) == 1


async def test_token_budget_remains_authoritative():
    model = ScriptedModel(
        [[ModelChunk(text="Working."), ModelChunk(usage=ModelUsage(10, 5))]]
    )
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done()],
    ).run("Task", token_budget=10)
    assert not result.completed and result.stop_reason is StopReason.TOKEN_BUDGET
    assert len(model.requests) == 1


@pytest.mark.parametrize("with_done", [False, True])
async def test_optional_limit_summary_remains_incomplete_and_unstructured(with_done):
    model = ScriptedModel(
        [call("done", success=True) if with_done else "Working.", "Partial summary"]
    )
    result = await Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done(), AgentLoop(final_step=FinalStepPolicy.SUMMARIZE)],
    ).run("Task", output=_Answer, max_steps=2)
    assert result.text == "Partial summary"
    assert not result.completed and result.stop_reason is StopReason.MAX_STEPS
    assert model.requests[-1].tools == ()
    assert model.requests[-1].output_schema is None
    with pytest.raises(OutputUnavailable):
        _ = result.output


async def test_each_turn_uses_its_own_completion_and_output_contract():
    model = ScriptedModel(
        [
            call("done", success=True),
            call("final_answer", title="Item", count=1),
            "Working again.",
            call("done", success=True),
            "Second answer",
        ]
    )
    async with Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[Done()],
    ).session() as session:
        first = await session.run("First task", output=_Answer)
        second = await session.run("Second task")
    assert first.output.count == 1
    assert second.completed and second.text == "Second answer"
    assert "done" in {tool.name for tool in model.requests[2].tools}
    assert model.requests[2].output_schema is None
    assert model.requests[-1].tools == ()


async def test_runtime_mount_and_removal_restore_native_completion_and_output():
    model = ScriptedModel(
        [
            "Commentary",
            call("done", success=True),
            "Plugin answer",
            call("final_answer", title="Native answer", count=1),
        ]
    )
    async with Agent(model=model).session() as session:
        handle = await session.use(Done(), section_delivery=SectionDelivery.CONTEXT)
        first = await session.run("Plugin task")
        await handle.aclose()
        second = await session.run("Native task", output=_Answer)
    assert first.completed and first.text == "Plugin answer"
    assert second.completed and second.output.title == "Native answer"
    assert [tool.name for tool in model.requests[-1].tools] == ["final_answer"]


def test_browser_facade_accepts_the_opt_in_plugin_without_changing_defaults():
    plain = browserrig.Agent(model=ScriptedModel([]))
    explicit = browserrig.Agent(model=ScriptedModel([]), plugins=[Done()])
    assert not any(isinstance(plugin, Done) for plugin in plain.plugins)
    assert sum(isinstance(plugin, Done) for plugin in explicit.plugins) == 1
