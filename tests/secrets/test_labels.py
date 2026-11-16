import pytest
from harnessed import Agent, Plugin, ToolCall, tool
from harnessed.events import ToolCallFinishedEvent, ToolCallRequestedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals, CallEnvelope
from harnessed.testing import ScriptedModel

from browserrig import ActionLabel, Secret, Secrets, action_label
from tests.fakes import FakeChrome


@pytest.mark.parametrize("denied", [False, True])
async def test_host_accessor_redacts_requested_and_finished_labels_automatically(
    denied,
):
    secret = "private-credential"
    request = ToolCall("read_report", {"action_label": f"Reading {secret}"})
    agent = Agent(
        model=ScriptedModel([[ModelChunk(tool_call=request)], "Done"]),
        plugins=[
            FakeChrome({}),
            _Report(),
            CallEnvelope(ActionLabel),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
            Approvals(deny=("read_report",)) if denied else None,
        ],
    )
    displayed = []
    async with agent.session() as session:

        def display(event):
            displayed.append((type(event), action_label(event, scope=session.scope)))

        session.scope.on(ToolCallRequestedEvent, display)
        session.scope.on(ToolCallFinishedEvent, display)
        await session.run("Read")
    assert displayed == [
        (ToolCallRequestedEvent, "Reading {{secret:KEY}}"),
        (ToolCallFinishedEvent, "Reading {{secret:KEY}}"),
    ]
    assert request.arguments["action_label"] == f"Reading {secret}"


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"action_label": "Reading the report"}, "Reading the report"),
        ({}, ""),
        ({"action_label": 42}, ""),
        ({"action_label": " "}, ""),
        ({"action_label": "x" * 81}, ""),
    ],
)
async def test_host_accessor_handles_labels_without_configured_secrets(
    arguments, expected
):
    agent = Agent(model=ScriptedModel([]))
    event = ToolCallRequestedEvent(call=ToolCall("read_report", arguments))
    async with agent.session() as session:
        assert action_label(event, scope=session.scope) == expected


async def test_host_accessor_uses_only_the_given_sessions_secrets():
    secret = "private-credential"
    event = ToolCallRequestedEvent(
        call=ToolCall("read_report", {"action_label": f"Reading {secret}"})
    )
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            FakeChrome({}),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
        ],
    )
    other = Agent(model=ScriptedModel([]))
    async with agent.session() as session, other.session() as unrelated:
        assert action_label(event, scope=session.scope) == "Reading {{secret:KEY}}"
        assert action_label(event, scope=unrelated.scope) == f"Reading {secret}"


class _Report(Plugin):
    @tool(readonly=True)
    async def read_report(self) -> str:
        return "Report"
