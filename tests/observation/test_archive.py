import json
import re
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel, call

from browserrig import (
    Browser,
    BrowserPerception,
    Files,
    FileSystem,
    LocalWorkspace,
    PageExtractionTools,
    Readiness,
    TextContext,
)
from browserrig.observation import CaptureContent, DomPerception, DomRenderer
from browserrig.observation import PageContent as CapturedPage
from browserrig.observation.archive import save_content
from browserrig.observation.content import PageContent
from browserrig.tools import WorkspaceTools
from browserrig.tools import extraction as extraction_module
from tests.fakes import FakeChrome


async def test_saved_snapshot_contains_content_beyond_the_tool_response(tmp_path):
    body = "Research line\n" * 4000 + "FINAL_SENTINEL"
    original = PageContent(
        url="https://example.org/report", title="Report", markdown=body
    )
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        saved = await save_content(files, original, full_page=False)
        first = saved.page(0, 100)
        assert "FINAL_SENTINEL" not in first.markdown and first.next_offset is not None
        assert "FINAL_SENTINEL" in (tmp_path / saved.extracted_path).read_text(
            encoding="utf-8"
        )
        metadata = json.loads(
            (tmp_path / saved.extracted_path).with_name("source.json").read_text()
        )
        assert metadata["url"] == original.url and metadata["full_page"] is False
        assert "markdown" not in metadata and metadata["captured_at"]
        assert saved.extracted_path in first.render()


async def test_receipt_keeps_page_body_out_of_context_and_search_reads_the_saved_text(
    tmp_path, monkeypatch
):
    body = "Research line\n" * 4000 + "FINAL_SENTINEL"
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/report",
            title="Report",
            markdown=body,
        )
    )
    monkeypatch.setattr(extraction_module, "extract_document", capture)
    agent = Agent(
        model=(
            model := ScriptedModel(
                [
                    call("extract_content"),
                    call("grep", query="FINAL_SENTINEL", pattern="pages/**/*.md"),
                    "Done",
                ]
            )
        ),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(capture=_Capture(), renderer=DomRenderer()),
            PageExtractionTools(),
            TextContext(),
            WorkspaceTools(),
        ],
    )
    async with agent.session() as session:
        observe = session.scope[PageExtractionTools]
        result = await session.run("Save the report, then find its final line")
        saved = observe.extracted_content
        assert saved is not None and saved.markdown == body
        replies = [
            event.result
            for event in result.events
            if isinstance(event, ToolCallFinishedEvent)
        ]
        assert len(replies) == 2 and all(not reply.is_error for reply in replies)
        assert replies[0].text == (
            f"Saved: {saved.extracted_path}\nSource: https://example.org/report\nTitle: Report"
        )
        assert "Research line" not in "\n".join(
            message.text for request in model.requests for message in request.messages
        )
        assert "FINAL_SENTINEL" in replies[1].text
        match = re.search(r"offset=(\d+)", replies[1].text)
        assert match is not None
        excerpt = await session.scope[FileSystem].read_file(
            saved.extracted_path, offset=int(match[1]), max_chars=500
        )
        assert "FINAL_SENTINEL" in excerpt.text and len(excerpt.text) <= 500
        capture.assert_awaited_once_with(
            session.scope[Browser].active_tab, full_page=False
        )


async def test_each_tool_call_saves_a_new_snapshot_without_changing_the_previous_file(
    tmp_path, monkeypatch
):
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/",
            title="Report",
            markdown="Original line\n" * 100,
        )
    )
    monkeypatch.setattr(extraction_module, "extract_document", capture)
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(capture=_Capture(), renderer=DomRenderer()),
            PageExtractionTools(),
            TextContext(),
        ],
    )
    async with agent.session() as session:
        observe = session.scope[PageExtractionTools]
        await observe.extract_content()
        first = observe.extracted_content
        capture.return_value = PageContent(
            url="https://example.org/", title="Report", markdown="Changed"
        )
        await observe.extract_content()
        latest = observe.extracted_content
        assert (
            latest.markdown == "Changed"
            and latest.extracted_path != first.extracted_path
        )
        assert (tmp_path / first.extracted_path).is_file()
        assert "Original line" in (tmp_path / first.extracted_path).read_text(
            encoding="utf-8"
        )
        assert capture.await_count == 2


async def test_extraction_is_unavailable_without_a_workspace():
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[FakeChrome({}), Readiness(), DomPerception()],
    )
    async with agent.session() as session:
        assert "extract_content" not in {
            tool.name for tool in session.scope[ToolRegistry].definitions
        }


async def test_save_failure_does_not_return_inline_content(tmp_path, monkeypatch):
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/", title="Report", markdown="BODY_SENTINEL"
        )
    )
    save = AsyncMock(side_effect=OSError("Storage unavailable"))
    monkeypatch.setattr(extraction_module, "extract_document", capture)
    monkeypatch.setattr(extraction_module, "save_content", save)
    agent = Agent(
        model=ScriptedModel([call("extract_content"), "Done"]),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(capture=_Capture(), renderer=DomRenderer()),
            PageExtractionTools(),
            TextContext(),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Save the report")
        assert session.scope[PageExtractionTools].extracted_content is None
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert reply.is_error and "could not be saved" in reply.text
    assert "BODY_SENTINEL" not in reply.text
    capture.assert_awaited_once()
    save.assert_awaited_once()


def test_saved_receipt_reports_only_actual_metadata_and_limitations():
    content = PageContent(
        url="https://example.org/report",
        title="Two\nlines",
        markdown="BODY_SENTINEL",
        extracted_path="pages/p17/content.md",
        limitations=("Frame f2 could not be inspected",),
    )
    assert content.render_receipt() == (
        "Saved: pages/p17/content.md\nSource: https://example.org/report\nTitle: Two lines\n\n"
        "Extraction limitations:\n- Frame f2 could not be inspected"
    )
    with pytest.raises(ValueError, match="workspace path"):
        content.model_copy(update={"extracted_path": None}).render_receipt()


async def test_named_snapshot_is_searchable_in_the_same_batch_and_replaced_on_resave(
    tmp_path, monkeypatch
):
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/reviews",
            title="Reviews",
            markdown="| 338 | Merrie | Antonia Racer Tank |",
        )
    )
    monkeypatch.setattr(extraction_module, "extract_document", capture)
    path = "pages/reviews/content.md"
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(
                        tool_call=ToolCall("extract_content", {"name": "reviews"})
                    ),
                    ModelChunk(
                        tool_call=ToolCall("grep", {"query": "Merrie", "pattern": path})
                    ),
                ],
                "Done",
            ]
        ),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(capture=_Capture(), renderer=DomRenderer()),
            PageExtractionTools(),
            TextContext(),
            WorkspaceTools(),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Save the reviews and find Merrie")
        saved, found = [
            event.result
            for event in result.events
            if isinstance(event, ToolCallFinishedEvent)
        ]
        assert saved.text.startswith(f"Saved: {path}\n")
        assert not found.is_error and f"{path}:" in found.text
        capture.return_value = PageContent(
            url="https://example.org/reviews?p=2", title="Reviews", markdown="Page two"
        )
        await session.scope[PageExtractionTools].extract_content(name="reviews")
    assert "Page two" in (tmp_path / path).read_text(encoding="utf-8")
    metadata = json.loads((tmp_path / "pages/reviews/source.json").read_text())
    assert metadata["url"] == "https://example.org/reviews?p=2"


@pytest.mark.parametrize("name", ["", "../escape", "a/b", "-dash", "x" * 65])
async def test_snapshot_names_cannot_leave_the_pages_directory(tmp_path, name):
    content = PageContent(url="https://example.org/", title="Page", markdown="Body")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        with pytest.raises(ValueError, match="snapshot name"):
            await save_content(files, content, full_page=False, name=name)
    assert not (tmp_path / "pages").exists()


class _Capture:
    async def collect(self, tab, _report, **_kwargs):
        return CaptureContent(
            page=CapturedPage(
                url=tab.url,
                title="Page",
                width=800,
                height=600,
                scroll_y=0,
                page_height=600,
            )
        )
