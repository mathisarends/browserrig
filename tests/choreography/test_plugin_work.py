from harnessed import Agent, Plugin, ToolCall, ToolError
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel

from browserrig import InputVisualization, Secret, Secrets
from browserrig.choreography import WorkPhase, WorkPresentedEvent
from browserrig.core import ActionKind, browser_tool
from browserrig.files import FileContent
from tests.fakes import FakeChrome


class _Reader(Plugin):
    def __init__(self, content):
        super().__init__()
        self.content = content

    @browser_tool(kind=ActionKind.READ_FILE, readonly=True, description="Read material")
    async def read_material(self, fail: bool = False) -> FileContent:
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
            InputVisualization(renderer=None),
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
        plugins=[FakeChrome({}), _Reader("unused"), InputVisualization(renderer=None)],
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
            InputVisualization(renderer=None),
            Approvals(deny=("read_material",)),
        ],
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        await session.run("Read")
    assert len(receipts) == 1 and receipts[0].phase is WorkPhase.FAILED
    assert receipts[0].tool_name == "read_material" and receipts[0].kind is None
