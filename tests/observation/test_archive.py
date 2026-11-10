import json
from unittest.mock import AsyncMock

from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import BrowserPerception, Files, FileSystem, LocalWorkspace, Readiness
from browserrig.observation import plugin as observation_plugin
from browserrig.observation.archive import save_content
from browserrig.observation.content import PageContent
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


async def test_offset_reads_reuse_the_saved_snapshot_and_zero_captures_a_new_one(
    tmp_path, monkeypatch
):
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/",
            title="Report",
            markdown="Original line\n" * 100,
        )
    )
    monkeypatch.setattr(observation_plugin, "extract_document", capture)
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(),
        ],
    )
    async with agent.session() as session:
        observe = session.scope[BrowserPerception]
        await observe.extract_content(max_chars=40)
        first = observe.extracted_content
        capture.return_value = PageContent(
            url="https://example.org/", title="Report", markdown="Changed"
        )
        await observe.extract_content(offset=first.next_offset, max_chars=40)
        second = observe.extracted_content
        assert (
            second.extracted_path == first.extracted_path
            and "Original" in second.markdown
        )
        capture.assert_awaited_once()
        await observe.extract_content(max_chars=40)
        latest = observe.extracted_content
        assert (
            latest.markdown == "Changed"
            and latest.extracted_path != first.extracted_path
        )
        assert (tmp_path / first.extracted_path).is_file()
        assert capture.await_count == 2
