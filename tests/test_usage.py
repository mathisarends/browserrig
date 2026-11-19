from harnessed import Agent, ToolCall
from harnessed.models import ModelChunk, ModelUsage
from harnessed.testing import ScriptedModel

from browserrig import TokenUsageTracker, TurnUsageEvent


async def test_tracker_reports_each_turns_aggregated_usage():
    model = ScriptedModel(
        [
            [
                ModelChunk(tool_call=ToolCall("unknown", {})),
                ModelChunk(usage=ModelUsage(40, 4, 20, 8, 2, 0.125)),
            ],
            [ModelChunk(text="First", usage=ModelUsage(60, 6, 30, 2, 3, 0.25))],
            [ModelChunk(text="Second", usage=ModelUsage(10, 1))],
        ]
    )
    agent = Agent(model=model, plugins=[TokenUsageTracker()])
    reports: list[TurnUsageEvent] = []
    async with agent.session() as session:
        session.on(TurnUsageEvent, reports.append)
        first = await session.run("First turn")
        second = await session.run("Second turn")

    assert first.usage == ModelUsage(100, 10, 50, 10, 5, 0.375)
    assert second.usage == ModelUsage(10, 1)
    assert reports == [
        TurnUsageEvent(first.turn_id, first.usage),
        TurnUsageEvent(second.turn_id, second.usage),
    ]
    assert all(
        not isinstance(event, TurnUsageEvent) for event in first.events + second.events
    )
