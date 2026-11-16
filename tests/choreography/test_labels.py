import asyncio

import pytest
from harnessed import Agent, Plugin, ToolCall, ToolChain, ToolError, ToolStatus, tool
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel
from pydantic import TypeAdapter

from browserrig import ActionLabels, Secret, Secrets
from browserrig.choreography import (
    ActionEnvelope,
    ToolCallPhase,
    ToolCallPresentedEvent,
)
from tests.fakes import FakeChrome


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("ok", ToolStatus.OK),
        ("error", ToolStatus.ERROR),
        ("denied", ToolStatus.DENIED),
        ("cancelled", ToolStatus.CANCELLED),
    ],
)
@pytest.mark.parametrize("secrets_first", [False, True])
async def test_stream_envelopes_are_redacted_before_emission_and_survive_session_close(
    outcome, status, secrets_first
):
    secret = "private-credential"
    request = ToolCall(
        "read_report",
        {
            "action_label": f"Reading {secret}",
            "fail": outcome == "error",
            "cancel": outcome == "cancelled",
        },
    )
    secrets = Secrets({"KEY": Secret(secret, domains=("example.org",))})
    plugins = [secrets, ActionLabels()] if secrets_first else [ActionLabels(), secrets]
    agent = Agent(
        model=ScriptedModel([[ModelChunk(tool_call=request)], "Done"]),
        plugins=[
            FakeChrome({}),
            _Report(),
            *plugins,
            Approvals(deny=("read_report",)) if outcome == "denied" else None,
        ],
    )
    displayed = []
    published = []
    async with agent.session() as session:
        session.scope.on(ToolCallPresentedEvent, published.append)
        async with session.stream("Read") as stream:
            async for event in stream:
                match event:
                    case ToolCallPresentedEvent() as event:
                        displayed.append((event.phase, event.envelope.action_label))
            result = await stream.result()
    assert displayed == [
        (ToolCallPhase.REQUESTED, "Reading {{secret:KEY}}"),
        (ToolCallPhase.FINISHED, "Reading {{secret:KEY}}"),
    ]
    assert len(published) == 2
    assert {event.envelope.action_label for event in published} == {
        "Reading {{secret:KEY}}"
    }
    assert {event.call_id for event in published} == {request.id}
    assert {event.tool_name for event in published} == {request.name}
    assert published[0].status is None and published[-1].status is status
    assert not any(isinstance(event, ToolCallPresentedEvent) for event in result.events)
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
async def test_display_events_need_no_browser_or_secrets_and_have_no_optional_envelope(
    arguments, expected
):
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_report", arguments))], "Done"]
        ),
        plugins=[ActionLabels(), _Report()],
    )
    events = []
    async with agent.session() as session:
        session.scope.on(ToolCallPresentedEvent, events.append)
        await session.run("Read")
    assert len(events) == 2
    assert {event.envelope.action_label for event in events} == {expected}
    assert events[-1].status is ToolStatus.OK


@pytest.mark.parametrize("enabled", [False, True])
async def test_schema_and_presentation_opt_in_together(enabled):
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_report", {}))], "Done"]
        ),
        plugins=[_Report(), ActionLabels() if enabled else None],
    )
    events = []
    async with agent.session() as session:
        session.scope.on(ToolCallPresentedEvent, events.append)
        definition = next(
            item
            for item in session.scope[ToolRegistry].definitions
            if item.name == "read_report"
        )
        assert ("action_label" in definition.parameters["properties"]) is enabled
        await session.run("Read")
    assert len(events) == (2 if enabled else 0)


async def test_skipped_calls_keep_their_display_envelope_without_execution():
    skipped = ToolCall("read_report", {"action_label": "Reading the report"})
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(tool_call=ToolCall("stop", {})),
                    ModelChunk(tool_call=skipped),
                ],
                "Done",
            ]
        ),
        plugins=[ActionLabels(), _Stop(), _Report()],
    )
    events = []
    async with agent.session() as session:
        session.scope.on(ToolCallPresentedEvent, events.append)
        await session.run("Read")
    updates = [event for event in events if event.call_id == skipped.id]
    assert [event.phase for event in updates] == [
        ToolCallPhase.REQUESTED,
        ToolCallPhase.FINISHED,
    ]
    assert {event.envelope.action_label for event in updates} == {"Reading the report"}
    assert updates[-1].status is ToolStatus.SKIPPED


async def test_shared_plugin_keeps_each_sessions_redaction_independent():
    secret = "private-credential"
    recipe = ActionLabels()
    request = {"action_label": f"Reading {secret}"}
    first = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_report", request))], "Done"]
        ),
        plugins=[
            recipe,
            _Report(),
            FakeChrome({}),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
        ],
    )
    second = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_report", request))], "Done"]
        ),
        plugins=[recipe, _Report()],
    )
    first_events = []
    second_events = []
    async with first.session() as one, second.session() as two:
        one.scope.on(ToolCallPresentedEvent, first_events.append)
        two.scope.on(ToolCallPresentedEvent, second_events.append)
        await asyncio.gather(one.run("Read"), two.run("Read"))
    assert len(first_events) == len(second_events) == 2
    assert {event.envelope.action_label for event in first_events} == {
        "Reading {{secret:KEY}}"
    }
    assert {event.envelope.action_label for event in second_events} == {
        f"Reading {secret}"
    }


def test_redacted_snapshot_serializes_as_a_typed_nested_envelope():
    event = ToolCallPresentedEvent(
        call_id="call",
        tool_name="read_report",
        phase=ToolCallPhase.REQUESTED,
        envelope=ActionEnvelope("Reading {{secret:" + "KEY" * 30 + "}}"),
    )
    adapter = TypeAdapter(ToolCallPresentedEvent)
    payload = adapter.dump_json(event)
    restored = adapter.validate_json(payload)
    assert restored == event
    assert isinstance(restored.envelope, ActionEnvelope)
    assert restored.envelope.action_label == event.envelope.action_label
    assert b'"envelope":{"action_label":' in payload


class _Report(Plugin):
    @tool(readonly=True)
    async def read_report(self, fail: bool = False, cancel: bool = False) -> str:
        if cancel:
            raise asyncio.CancelledError
        if fail:
            raise ToolError("Report unavailable")
        return "Report"


class _Stop(Plugin):
    @tool(readonly=True, chain=ToolChain.STOP_AFTER)
    async def stop(self) -> str:
        return "Stopped"
