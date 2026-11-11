from dataclasses import replace

import pytest
from harnessed import Agent, PolicyDecision
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ImagePart, ImageReference
from harnessed.plugins import Approvals
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel, call
from PIL import Image

from browserrig import BrowserFileTools, Files, LocalWorkspace, WorkspaceTools
from browserrig.browser import Browser
from browserrig.events import FileReadFinishedEvent, FileWrittenEvent
from browserrig.files import FileSystem, MountedWorkspace
from browserrig.tools import Actions
from tests.fakes import FakeServices, mounted


class _WorkspaceTools(WorkspaceTools, provides=True):
    """Expose the mounted plugin, so tests can call its tools directly."""


async def test_read_file_delivers_an_image_part_to_the_model(tmp_path):
    Image.new("RGB", (30, 20), "blue").save(tmp_path / "image.png")
    model = ScriptedModel([call("read_file", path="image.png"), "Seen"])
    agent = Agent(
        model=model, plugins=[Files(LocalWorkspace(tmp_path)), WorkspaceTools()]
    )
    async with agent.session() as session:
        result = await session.run("Inspect the image")
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert not reply.is_error and "data:image" not in reply.text
    assert any(isinstance(part, ImagePart | ImageReference) for part in reply.content)
    assert any(
        isinstance(part, ImagePart | ImageReference)
        for message in model.requests[-1].messages
        if not isinstance(message.content, str)
        for part in message.content
    )


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
            "edit_file",
            "glob",
            "grep",
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


async def test_grep_tool_delivers_bounded_matches_with_readable_offsets(tmp_path):
    (tmp_path / "note.md").write_text("Research sentinel", encoding="utf-8")
    agent = Agent(
        model=ScriptedModel([call("grep", query="sentinel"), "Found"]),
        plugins=[Files(LocalWorkspace(tmp_path)), WorkspaceTools()],
    )
    async with agent.session() as session:
        result = await session.run("Find the research note")
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert (
        not reply.is_error and "note.md:1:" in reply.text and "offset=0" in reply.text
    )


@pytest.mark.parametrize("with_browser", [False, True])
async def test_workspace_tools_show_downloads_only_with_a_browser(
    tmp_path, with_browser
):
    model = ScriptedModel(["Done"])
    browser = [FakeServices()] if with_browser else []
    agent = Agent(
        model=model,
        plugins=[*browser, Files(LocalWorkspace(tmp_path)), WorkspaceTools()],
    )
    async with agent.session() as session:
        await session.run("Check the downloads")
    observed = [
        message.text
        for message in model.requests[0].messages
        if message.text.startswith("file_system:\n")
    ]
    assert len(observed) == (1 if with_browser else 0)


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
