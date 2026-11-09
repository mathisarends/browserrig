from dataclasses import replace

from harnessed import Agent, PolicyDecision
from harnessed.events import ToolCallFinishedEvent
from harnessed.plugins import Approvals
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel, call

from browserrig import BrowserFileTools, Files, LocalWorkspace, WorkspaceTools
from browserrig.browser import Browser
from browserrig.events import FileReadFinishedEvent, FileWrittenEvent
from browserrig.files import FileSystem, MountedWorkspace
from browserrig.tools import Actions
from tests.fakes import mounted


class _WorkspaceTools(WorkspaceTools, provides=True):
    """Expose the mounted plugin, so tests can call its tools directly."""


async def test_workspace_tools_run_without_browser_or_action_services(tmp_path):
    model = ScriptedModel(
        [
            call("write_file", path="note.txt", content="Workspace only"),
            call("read_file", path="note.txt"),
            "Finished",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            WorkspaceTools(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        assert Browser not in session.scope and Actions not in session.scope
        assert {tool.name for tool in session.scope[ToolRegistry].definitions} == {
            "list_files",
            "read_file",
            "write_file",
        }
        result = await session.run("Save and read a note")
        assert (
            await session.scope[FileSystem].read_file("note.txt")
        ).text == "Workspace only"
    replies = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert len(replies) == 2 and all(not reply.is_error for reply in replies)
    assert "Workspace only" in replies[-1].text
    assert any(isinstance(event, FileWrittenEvent) for event in result.events)
    assert any(isinstance(event, FileReadFinishedEvent) for event in result.events)


async def test_workspace_receipts_pass_through_the_browser_when_one_is_composed(
    tmp_path,
):
    async with (
        FileSystem(LocalWorkspace(tmp_path)) as files,
        mounted(_WorkspaceTools(), files=files) as (services, scope),
    ):
        # Stands in for a filter such as Secrets redaction.
        services.browser.events.add_filter(lambda event: replace(event, path="***"))
        await scope[_WorkspaceTools].write_file("secret.txt", "value")
    (written,) = services.events
    assert isinstance(written, FileWrittenEvent)
    assert written.browser_id == services.browser.id and written.path == "***"


async def test_browser_file_tools_do_not_expose_workspace_io(tmp_path):
    async with (
        FileSystem(LocalWorkspace(tmp_path)) as files,
        mounted(
            Actions(), BrowserFileTools(), files=files, bridge=MountedWorkspace()
        ) as (_, scope),
    ):
        assert {tool.name for tool in scope[ToolRegistry].definitions} == {
            "list_downloads",
            "open_file",
            "open_downloaded_file",
            "upload_files",
        }
