import io
import json

from harnessed import Agent, Inject, Plugin, SessionLog, hook
from harnessed.events import ModelRequestedEvent
from harnessed.testing import ScriptedModel

from browserrig import TerminalEvents
from browserrig.events import INPUT_EVENTS, KeyPressedEvent


async def test_terminal_observes_native_and_live_events_without_model_or_log_pollution():
    class Choreography(Plugin, needs=(SessionLog,)):
        events = INPUT_EVENTS

        @hook(ModelRequestedEvent)
        async def input(self, _event: ModelRequestedEvent, log: Inject[SessionLog]):
            await log.emit(KeyPressedEvent(key="x", action_id="action-1"))

    output = io.StringIO()
    model = ScriptedModel(["Final answer"])
    agent = Agent(model=model, plugins=[TerminalEvents(output), Choreography()])
    async with agent.session() as session:
        result = await session.run("PRIVATE PROMPT")
        assert result.text == "Final answer"
        assert not any(isinstance(event, KeyPressedEvent) for event in session.events)
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    key = next(record for record in records if record["type"] == "browser.key.pressed")
    assert key["key"] == "x" and key["action_id"] == "action-1"
    assert any(
        record["type"] == ModelRequestedEvent.__dataclass_fields__["type"].default
        for record in records
    )
    assert "PRIVATE PROMPT" not in output.getvalue()
    assert "Final answer" not in output.getvalue()
