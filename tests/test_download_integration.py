import asyncio
import base64
from pathlib import Path

import pytest
import yaml
from harnessed import PolicyDecision, ToolCall
from harnessed.models import ImagePart, ModelChunk, ToolReply
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Browser,
    BrowserAgent,
    ChromeBrowser,
    DomMode,
    FileSystemOptions,
    LaunchBrowser,
    ReadinessOptions,
    wait_for_page,
)
from browserrig.browser import DownloadState
from browserrig.browser.images import screenshot
from browserrig.events import DownloadCompletedEvent, DownloadStartedEvent
from tests.javascript import evaluate
from tests.observations import all_states

pytestmark = pytest.mark.integration


async def test_agent_uploads_workspace_files_and_rejects_a_mixed_outside_selection(site, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    stage = 0

    async def respond(request):
        nonlocal stage
        page = all_states(request.messages)[-1]
        replies = [message for message in request.messages if isinstance(message, ToolReply)]
        if stage == 2:
            assert not replies[-1].is_error
            assert (
                await evaluate(browser.active_tab, "document.querySelector('#upload').files.length")
                == 1
            )
            assert (
                await evaluate(
                    browser.active_tab, "document.querySelector('#upload').files[0].name"
                )
                == "report.txt"
            )
            yield ModelChunk(text="Only the workspace file was uploaded")
            return
        if stage == 1:
            assert replies[-1].is_error and "outside" in replies[-1].text
            assert (
                await evaluate(browser.active_tab, "document.querySelector('#upload').files.length")
                == 0
            )
        refs = [
            element["ref"] for element in page["elements"] if element["name"] == "Upload report"
        ]
        assert len(refs) == 1
        ref = refs[0]
        paths = ["report.txt", str(secret)] if stage == 0 else ["report.txt"]
        stage += 1
        yield ModelChunk(tool_call=ToolCall("upload_files", {"ref": ref, "paths": paths}))

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        file_system=FileSystemOptions(directory=workspace),
        approvals=Approvals(default=PolicyDecision.ALLOW),
    )
    async with agent.session() as session:
        browser = session.ctx[Browser]
        await evaluate(
            browser.active_tab,
            "(() => {const input=document.createElement('input');input.type='file';"
            "input.id='upload';input.setAttribute('aria-label','Upload report');"
            "document.body.prepend(input);return true})()",
        )
        result = await session.run("Upload the report", max_steps=3)
    assert result.text == "Only the workspace file was uploaded"


async def test_downloaded_workbook_is_read_as_context_without_browser_preview(site, tmp_path):
    async with ChromeBrowser(
        LaunchBrowser(url=site), file_system=FileSystemOptions(directory=tmp_path / "workspace")
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            "(() => {const a=document.createElement('a');a.href='/download-xlsx';"
            "a.download='report.xlsx';a.click();return true})()",
        )
        async with asyncio.timeout(10):
            while (
                not (downloads := await browser.downloads())
                or downloads[-1].state != DownloadState.COMPLETED
            ):
                await asyncio.sleep(0.02)
        document = await asyncio.to_thread(
            browser.files.read_file, downloads[-1].path, sheet="Revenue", cell_range="A1:C2"
        )
        assert "Voyager" in document.text and "=B2*2" in document.text
        assert document.extracted_path and Path(document.extracted_path).is_file()
        assert len(await browser.tabs()) == 1 and browser.active_tab.id == tab.id


async def test_agent_reads_selected_workbook_cells_as_context(site, tmp_path, xlsx_document):
    (tmp_path / "report.xlsx").write_bytes(xlsx_document)
    stage = 0

    async def respond(request):
        nonlocal stage
        if stage == 0:
            stage += 1
            yield ModelChunk(
                tool_call=ToolCall(
                    "read_file", {"path": "report.xlsx", "sheet": "Revenue", "cell_range": "A1:C2"}
                )
            )
            return
        replies = [message for message in request.messages if isinstance(message, ToolReply)]
        assert not replies[-1].is_error and "Voyager" in replies[-1].text
        assert "=B2*2" in replies[-1].text
        assert not any(
            isinstance(part, ImagePart)
            for message in request.messages
            if not isinstance(message.content, str)
            for part in message.content
        )
        yield ModelChunk(text="Workbook read as context")

    result = await BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        file_system=FileSystemOptions(directory=tmp_path),
        approvals=Approvals(default=PolicyDecision.ALLOW),
    ).run("Read the downloaded workbook", max_steps=2)
    assert result.text == "Workbook read as context"


async def test_scoped_download_has_enum_state_and_namespaced_events(site, tmp_path):
    received = []

    async def collect(event):
        received.append(event)

    async with ChromeBrowser(
        LaunchBrowser(url=site, download_directory=str(tmp_path)), emit=collect
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            "(() => {const a=document.createElement('a');a.href='/download';"
            "a.download='example.txt';a.click();return true})()",
        )
        async with asyncio.timeout(5):
            while True:
                downloads = await browser.downloads()
                if downloads and downloads[0].state is DownloadState.COMPLETED:
                    break
                await asyncio.sleep(0.02)
        assert downloads[0].received_bytes == len(b"download payload")
        assert downloads[0].path is not None
        assert Path(downloads[0].path).read_bytes() == b"download payload"
        assert any(isinstance(event, DownloadStartedEvent) for event in received)
        assert any(isinstance(event, DownloadCompletedEvent) for event in received)


async def test_default_downloads_can_be_read_and_viewed_as_pdf_in_a_new_tab(site, tmp_path):
    async with ChromeBrowser(
        LaunchBrowser(url=site), file_system=FileSystemOptions(directory=tmp_path / "workspace")
    ) as browser:
        original = browser.active_tab
        await wait_for_page(original)
        await evaluate(original, "document.querySelector('#download').click()")
        async with asyncio.timeout(10):
            while (
                not (downloads := await browser.downloads())
                or downloads[-1].state != DownloadState.COMPLETED
            ):
                await asyncio.sleep(0.02)
        downloaded = downloads[-1]
        assert downloaded.error is None
        document = browser.files.read_file(downloaded.path, page_number=2)
        assert "Second page: Voyager 2" in document.text
        opened = await browser.open_tab(browser.files.resolve(downloaded.path))
        await wait_for_page(opened)
        assert opened.id != original.id
        assert opened.url == Path(downloaded.path).as_uri()
        assert await evaluate(opened, "document.contentType") == "application/pdf"
        assert original.url == site + "/"
        assert len(await browser.tabs()) == 2
        image = await screenshot(opened)
        assert len(image) > 1000
        (tmp_path / "pdf-preview.png").write_bytes(base64.b64decode(image))
    assert Path(downloaded.path).is_file()


async def test_agent_downloads_reads_previews_and_returns_to_its_original_tab(site, tmp_path):
    stage = 0
    original_tab = ""
    downloaded_path = ""

    async def respond(request):
        nonlocal stage, original_tab, downloaded_path
        page = all_states(request.messages)[-1]
        files = [
            yaml.safe_load(message.text)["file_system"]
            for message in request.messages
            if message.text.startswith("file_system:\n")
        ][-1]
        replies = [message for message in request.messages if isinstance(message, ToolReply)]
        assert all(not reply.is_error for reply in replies)
        if stage == 0:
            assert {
                "list_files",
                "read_file",
                "write_file",
                "open_file",
                "open_downloaded_file",
            } <= {item.name for item in request.tools}
            original_tab = page["page"]["tab"]
            link = [element for element in page["elements"] if element["name"] == "Download PDF"][0]
            tool_call = ToolCall("click", {"ref": link["ref"]})
        elif stage == 1:
            downloads = files["downloads"]
            if not downloads or downloads[-1]["state"] != "completed":
                yield ModelChunk(tool_call=ToolCall("list_downloads", {}))
                return
            downloaded_path = downloads[-1]["path"]
            tool_call = ToolCall("read_file", {"path": downloaded_path, "page_number": 2})
        elif stage == 2:
            assert "Second page: Voyager 2" in replies[-1].text
            tool_call = ToolCall(
                "open_downloaded_file", {"download_id": files["downloads"][-1]["id"]}
            )
        elif stage == 3:
            assert page["page"]["url"] == Path(downloaded_path).as_uri()
            assert page["page"]["tab"] != original_tab
            tool_call = ToolCall("screenshot", {})
        elif stage == 4:
            assert any(
                isinstance(part, ImagePart)
                for message in request.messages
                if not isinstance(message.content, str)
                for part in message.content
            )
            tool_call = ToolCall("switch_tab", {"target_id": original_tab})
        elif stage == 5:
            assert page["page"]["tab"] == original_tab
            tool_call = ToolCall(
                "write_file", {"path": "notes/summary.md", "content": "Voyager 2 research"}
            )
        elif stage == 6:
            tool_call = ToolCall("read_file", {"path": "notes/summary.md"})
        else:
            assert "Voyager 2 research" in replies[-1].text
            yield ModelChunk(text="PDF inspected and notes saved")
            return
        stage += 1
        yield ModelChunk(tool_call=tool_call)

    model = CallbackModel(respond)
    agent = BrowserAgent(
        model=model,
        browser=LaunchBrowser(url=site),
        file_system=FileSystemOptions(directory=tmp_path / "workspace"),
        approvals=Approvals(default=PolicyDecision.ALLOW),
    )
    result = await agent.run("Download the PDF, inspect it and save notes", max_steps=30)
    assert result.text == "PDF inspected and notes saved"
    assert (tmp_path / "workspace/notes/summary.md").read_text() == "Voyager 2 research"


async def test_agent_previews_pdf_with_full_viewport_and_returns_to_original_tab(
    site, tmp_path, pdf_document
):
    (tmp_path / "report.pdf").write_bytes(pdf_document)
    stage = 0
    original_tab = ""

    async def respond(request):
        nonlocal stage, original_tab
        page = all_states(request.messages)[-1]["page"]
        replies = [message for message in request.messages if isinstance(message, ToolReply)]
        assert all(not reply.is_error for reply in replies)
        if stage == 0:
            original_tab = page["tab"]
            assert "upload_files" in {item.name for item in request.tools}
            tool_call = ToolCall("open_file", {"path": "report.pdf"})
        elif stage == 1:
            assert page["url"] == (tmp_path / "report.pdf").as_uri()
            assert page["readiness"] == "ready"
            images = [
                message for message in request.messages if message.id.startswith("browser-image:")
            ]
            assert len(images) == 1
            tool_call = ToolCall("switch_tab", {"target_id": original_tab})
        else:
            assert page["tab"] == original_tab
            assert page["readiness"] == "ready"
            yield ModelChunk(text="Back on original tab")
            return
        stage += 1
        yield ModelChunk(tool_call=tool_call)

    result = await BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site + "/canvas"),
        mode=DomMode(screenshots=True),
        readiness=ReadinessOptions(timeout=3),
        file_system=FileSystemOptions(directory=tmp_path),
        approvals=Approvals(default=PolicyDecision.ALLOW),
    ).run("Preview the PDF and return to the original tab", max_steps=3)
    assert result.text == "Back on original tab"
