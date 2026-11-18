import pytest
from harnessed import Agent, Plugin, StopReason, tool
from harnessed.models import ModelRequest
from harnessed.plugins import AgentLoop, FinalStepPolicy
from harnessed.testing import ScriptedModel, call

from browserrig import Done, StepBudgetHints


class _Inspect(Plugin):
    @tool(readonly=True)
    async def inspect(self) -> str:
        return "Item found"


@pytest.mark.parametrize(
    ("final_step", "closing", "visible"),
    [
        (FinalStepPolicy.NONE, 7, [True, False, False, True, True, True, False, False]),
        (FinalStepPolicy.SUMMARIZE, 6, [True, False, True, True, True, False, False]),
    ],
)
async def test_warns_during_work_and_yields_to_done_at_closing(
    final_step, closing, visible
):
    model = ScriptedModel(
        [call("inspect")] * (closing - 1) + [call("done", success=True), "Final"]
    )
    agent = Agent(
        model=model,
        plugins=[
            AgentLoop(max_steps=8, final_step=final_step),
            StepBudgetHints(),
            Done(),
            _Inspect(),
        ],
    )

    result = await agent.run("Find the item.")

    assert result.completed and result.text == "Final"
    assert [bool(_hints(request)) for request in model.requests] == visible
    assert _hints(model.requests[0]) == [
        "Model step 1 of 8. Finish as soon as the task is complete."
    ]
    first_warning = _hints(model.requests[closing - 4])
    assert len(first_warning) == 1
    assert (
        f"Model step {closing - 3} of 8. 3 work steps left, including this step."
        in first_warning[0]
    )
    assert any(
        "Call done alone now" in message.text
        for message in model.requests[closing - 1].messages
    )


async def test_every_step_uses_current_turn_limit_and_keeps_only_the_current_hint():
    model = ScriptedModel(
        ["First", call("inspect"), call("inspect"), call("inspect"), "Final"]
    )
    agent = Agent(
        model=model,
        plugins=[
            AgentLoop(max_steps=12),
            StepBudgetHints(warn_at_remaining=1, show_every_step=True),
            _Inspect(),
        ],
    )

    async with agent.session() as session:
        await session.run("First task.")
        result = await session.run("Next task.", max_steps=4)

    assert result.completed and result.text == "Final"
    assert [_hints(request) for request in model.requests] == [
        ["Model step 1 of 12. Finish as soon as the task is complete."],
        ["Model step 1 of 4. Finish as soon as the task is complete."],
        ["Model step 2 of 4."],
        [
            "Model step 3 of 4. 1 work step left, including this step. "
            "Prioritize the most important remaining check and prepare to finish."
        ],
        ["Model step 4 of 4. Return the final answer now. Report any unfinished work."],
    ]


async def test_early_done_suppresses_the_countdown_in_the_final_answer_request():
    model = ScriptedModel([call("done", success=True), "Final"])
    agent = Agent(model=model, plugins=[Done(), StepBudgetHints(show_every_step=True)])

    result = await agent.run("Finish as soon as possible.", max_steps=10)

    assert result.completed and result.text == "Final"
    assert _hints(model.requests[0])
    assert _hints(model.requests[1]) == []


async def test_native_final_summary_owns_the_final_step_without_done():
    model = ScriptedModel([call("inspect"), "Partial summary"])
    agent = Agent(
        model=model,
        plugins=[
            AgentLoop(final_step=FinalStepPolicy.SUMMARIZE),
            StepBudgetHints(),
            _Inspect(),
        ],
    )

    result = await agent.run("Find the item.", max_steps=2)

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.text == "Partial summary"
    assert _hints(model.requests[0])
    assert _hints(model.requests[1]) == []
    assert model.requests[1].tools == ()


def _hints(request: ModelRequest) -> list[str]:
    return [
        message.text
        for message in request.messages
        if message.text.startswith("Model step ")
    ]
