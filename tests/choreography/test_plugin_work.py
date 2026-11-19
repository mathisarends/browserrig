import asyncio

import pytest
from harnessed import Agent, Plugin, ToolCall, ToolError, envelope_value, tool
from harnessed.events import ToolCallFinishedEvent, ToolCallRequestedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals, CallEnvelope
from harnessed.testing import ScriptedModel
from harnessed.tools import ToolRegistry

from browserrig import ActionLabel, Choreography, Secret, Secrets
from browserrig.choreography import WorkPhase, WorkPresentedEvent
from browserrig.core import ActionKind, browser_tool
from browserrig.files import FileContent
from tests.fakes import FakeChrome


class _Reader(Plugin):
    def __init__(self, content):
        super().__init__()
        self.content = content

    @browser_tool(kind=ActionKind.READ_FILE, readonly=True, description="Read material")
    async def read_material(
        self, fail: bool = False, cancel: bool = False
    ) -> FileContent:
        if cancel:
            raise asyncio.CancelledError
        if fail:
            raise ToolError("Material unavailable")
        return FileContent(
            path="report.txt", media_type="text/plain", text=self.content
        )


async def test_external_receipts_are_redacted_before_preview_truncation():
    secret = "sensitive-credential-at-preview-boundary"
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_material", {}))], "Done"]
        ),
        plugins=[
            FakeChrome({}),
            _Reader("x" * 1790 + secret),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
            Choreography(),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        result = await session.run("Read")
    assert result.text == "Done" and len(receipts) == 2
    assert receipts[-1].phase is WorkPhase.COMPLETED
    assert "sensitive-" not in receipts[-1].preview
    assert "{{secret:" in receipts[-1].preview
    assert not any(isinstance(event, WorkPresentedEvent) for event in result.events)


async def test_external_receipts_close_on_tool_validation_or_execution_error():
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_material", {"fail": True}))], "Done"]
        ),
        plugins=[FakeChrome({}), _Reader("unused"), Choreography()],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Read")
    assert [receipt.phase for receipt in receipts] == [
        WorkPhase.RUNNING,
        WorkPhase.FAILED,
    ]
    assert "Material unavailable" in receipts[-1].preview


async def test_denied_call_is_visible_without_faking_an_execution_start():
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_material", {}))], "Done"]
        ),
        plugins=[
            FakeChrome({}),
            _Reader("unused"),
            Choreography(),
            Approvals(deny=("read_material",)),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Read")
    assert len(receipts) == 1 and receipts[0].phase is WorkPhase.FAILED
    assert receipts[0].tool_name == "read_material" and receipts[0].kind is None


@pytest.mark.parametrize("name", ["read_material", "foreign_tool"])
async def test_model_labels_reach_host_events_without_becoming_tool_arguments(
    name,
):
    request = ToolCall(name, {"action_label": "Reading the annual report"})
    agent = Agent(
        model=ScriptedModel([[ModelChunk(tool_call=request)], "Done"]),
        plugins=[
            FakeChrome({}),
            _Reader("Report"),
            _Foreign(),
            Choreography(),
            CallEnvelope(ActionLabel),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        result = await session.run("Read")
    if name == "read_material":
        assert [receipt.phase for receipt in receipts] == [
            WorkPhase.RUNNING,
            WorkPhase.COMPLETED,
        ]
        assert {receipt.title for receipt in receipts} == {"Reading file"}
        assert {receipt.label for receipt in receipts} == {"Reading the annual report"}
        assert {receipt.call_id for receipt in receipts} == {request.id}
    else:
        assert not receipts
    events = [
        event
        for event in result.events
        if isinstance(event, (ToolCallRequestedEvent, ToolCallFinishedEvent))
    ]
    assert len(events) == 2
    assert all(
        envelope_value(event.call, ActionLabel).action_label
        == "Reading the annual report"
        for event in events
    )
    assert result.text == "Done"


@pytest.mark.parametrize(
    "arguments",
    [{}, {"action_label": 42}, {"action_label": " "}, {"action_label": "x" * 81}],
)
async def test_missing_or_invalid_labels_keep_existing_presentation(arguments):
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("read_material", arguments))], "Done"]
        ),
        plugins=[
            FakeChrome({}),
            _Reader("Report"),
            Choreography(),
            CallEnvelope(ActionLabel),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Read")
    assert [receipt.phase for receipt in receipts] == [
        WorkPhase.RUNNING,
        WorkPhase.COMPLETED,
    ]
    assert {receipt.title for receipt in receipts} == {"Reading file"}
    assert {receipt.label for receipt in receipts} == {""}


@pytest.mark.parametrize("denied", [False, True])
async def test_labels_are_redacted_for_executed_and_denied_calls(denied):
    secret = "private-credential"
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(
                        tool_call=ToolCall(
                            "read_material", {"action_label": f"Reading {secret}"}
                        )
                    )
                ],
                "Done",
            ]
        ),
        plugins=[
            FakeChrome({}),
            _Reader("Report"),
            Choreography(),
            CallEnvelope(ActionLabel),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
            Approvals(deny=("read_material",)) if denied else None,
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Read")
    assert len(receipts) == (1 if denied else 2)
    assert {receipt.title for receipt in receipts} == {
        "Tool not executed" if denied else "Reading file"
    }
    assert {receipt.label for receipt in receipts} == {"Reading {{secret:KEY}}"}
    assert receipts[-1].phase is (WorkPhase.FAILED if denied else WorkPhase.COMPLETED)


async def test_cancelled_tool_keeps_its_label():
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(
                        tool_call=ToolCall(
                            "read_material",
                            {"cancel": True, "action_label": "Waiting for the report"},
                        )
                    )
                ],
                "Done",
            ]
        ),
        plugins=[
            FakeChrome({}),
            _Reader("Report"),
            Choreography(),
            CallEnvelope(ActionLabel),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Wait")
    assert [receipt.phase for receipt in receipts] == [
        WorkPhase.RUNNING,
        WorkPhase.CANCELLED,
    ]
    assert {receipt.label for receipt in receipts} == {"Waiting for the report"}
    assert {receipt.title for receipt in receipts} == {"Reading file"}


@pytest.mark.parametrize("enabled", [False, True])
async def test_label_schema_is_opt_in_without_adding_foreign_tool_presentation(enabled):
    arguments = {"action_label": "Reading the report"} if enabled else {}
    agent = Agent(
        model=ScriptedModel(
            [[ModelChunk(tool_call=ToolCall("foreign_tool", arguments))], "Done"]
        ),
        plugins=[
            FakeChrome({}),
            _Foreign(),
            Choreography(),
            CallEnvelope(ActionLabel) if enabled else None,
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        schema = next(
            definition.parameters
            for definition in session.scope[ToolRegistry].definitions
            if definition.name == "foreign_tool"
        )
        assert ("action_label" in schema["properties"]) is enabled
        result = await session.run("Read")
    assert not receipts
    reply = next(
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    )
    assert reply.text == "Report" and not reply.is_error


class _Foreign(Plugin):
    @tool(readonly=True)
    async def foreign_tool(self) -> str:
        return "Report"
