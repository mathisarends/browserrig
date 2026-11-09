import asyncio
import base64
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path, PurePath, PurePosixPath

import pytest
import yaml
from harnessed import PolicyDecision, ToolCall
from harnessed.models import ImagePart, ModelChunk, ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Agent,
    Browser,
    BrowserDownload,
    BrowserPerception,
    Chrome,
    ChromeBrowser,
    Files,
    FileSystem,
    FileTransfer,
    LocalWorkspace,
    Readiness,
    ReadinessOptions,
    Screenshots,
    ScreenshotTrigger,
    Workspace,
    wait_for_page,
)
from browserrig.browser import DownloadState, Launch, screenshot
from browserrig.core import BrowserError
from browserrig.events import DownloadCompletedEvent, DownloadStartedEvent
from browserrig.observation import DomCapture, DomReferences, capture
from tests.javascript import evaluate
from tests.observations import all_states, has_image

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "mode", ["visible", "hidden", "transparent", "covered", "label", "nested"]
)
async def test_agent_uploads_workspace_files_and_rejects_a_mixed_outside_selection(
    site, tmp_path, mode
):
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
        replies = [
            message for message in request.messages if isinstance(message, ToolMessage)
        ]
        if stage == 2:
            assert not replies[-1].is_error
            assert (
                await evaluate(
                    browser.active_tab, "document.querySelector('#upload').files.length"
                )
                == 1
            )
            assert (
                await evaluate(
                    browser.active_tab,
                    "document.querySelector('#upload').files[0].name",
                )
                == "report.txt"
            )
            assert (
                await evaluate(
                    browser.active_tab,
                    "document.querySelector('#other-upload').files.length",
                )
                == 0
            )
            yield ModelChunk(text="Only the workspace file was uploaded")
            return
        if stage == 1:
            assert replies[-1].is_error and "outside" in replies[-1].text
            assert (
                await evaluate(
                    browser.active_tab, "document.querySelector('#upload').files.length"
                )
                == 0
            )
        refs = [
            element["ref"]
            for element in page["elements"]
            if element["name"] == "Upload report"
            and (element["in_viewport"] if mode in {"label", "nested"} else True)
        ]
        assert len(refs) == 1
        ref = refs[0]
        paths = ["report.txt", str(secret)] if stage == 0 else ["report.txt"]
        stage += 1
        yield ModelChunk(
            tool_call=ToolCall("upload_files", {"ref": ref, "paths": paths})
        )

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(workspace)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        await evaluate(
            browser.active_tab,
            """(() => {
                const input = document.createElement('input');
                input.type = 'file'; input.id = 'upload';
                input.setAttribute('aria-label', 'Upload report');
                document.body.prepend(input);
                const other = document.createElement('input');
                other.type = 'file'; other.id = 'other-upload';
                other.setAttribute('aria-label', 'Other attachment');
                document.body.append(other);
                return true;
            })()""",
        )
        modifications = {
            "visible": "true",
            "hidden": "document.querySelector('#upload').style.display = 'none'",
            "transparent": "document.querySelector('#upload').style.opacity = '0'",
            "covered": """(() => {
                const input = document.querySelector('#upload');
                const rect = input.getBoundingClientRect();
                const cover = document.createElement('div');
                Object.assign(cover.style, {position:'fixed',background:'white',zIndex:999,
                    left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px'});
                document.body.append(cover);
            })()""",
            "label": """(() => {
                document.querySelector('#upload').style.display = 'none';
                document.body.insertAdjacentHTML('afterbegin',
                    '<label for="upload">Upload report</label>');
            })()""",
            "nested": """(() => {
                const input = document.querySelector('#upload'); input.style.display = 'none';
                const label = document.createElement('label'); label.textContent = 'Upload report';
                input.before(label); label.append(input);
            })()""",
        }
        await evaluate(browser.active_tab, modifications[mode])
        result = await session.run("Upload the report", max_steps=3)
    assert result.text == "Only the workspace file was uploaded"


@pytest.mark.parametrize("invalid", ["disabled", "multiple", "retargeted"])
async def test_upload_validates_the_live_input_before_assigning_files(
    site, tmp_path, invalid
):
    report = tmp_path / "report.txt"
    report.write_text("report")
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """document.body.innerHTML =
            '<label for="upload">Report</label><input type="file" id="upload" hidden>' +
            '<input id="text">';""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
        label = next(element for element in state.elements if element.tag == "label")
        handle = await DomReferences().resolve(tab, state, label.ref)
        changes = {
            "disabled": "document.querySelector('#upload').disabled = true",
            "multiple": "true",
            "retargeted": "document.querySelector('label').htmlFor = 'text'",
        }
        await evaluate(tab, changes[invalid])
        codes = {
            "disabled": "ELEMENT_DISABLED",
            "multiple": "FILE_INPUT_NOT_MULTIPLE",
            "retargeted": "NOT_FILE_INPUT",
        }
        paths = [str(report)] * (2 if invalid == "multiple" else 1)
        with pytest.raises(BrowserError, match=codes[invalid]):
            await handle.upload_files(paths)
        assert (
            await evaluate(tab, "document.querySelector('#upload').files.length") == 0
        )


async def test_downloaded_workbook_is_read_as_context_without_browser_preview(
    site, tmp_path
):
    async with _receiving(Launch(url=site), LocalWorkspace(tmp_path / "workspace")) as (
        browser,
        files,
        _,
    ):
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
        document = await files.read_file(
            downloads[-1].path,
            sheet="Revenue",
            cell_range="A1:C2",
        )
        assert "Voyager" in document.text and "=B2*2" in document.text
        assert document.extracted_path
        assert (tmp_path / "workspace" / document.extracted_path).is_file()
        assert len(await browser.tabs.list()) == 1 and browser.active_tab.id == tab.id


async def test_agent_reads_selected_workbook_cells_as_context(
    site, tmp_path, xlsx_document
):
    (tmp_path / "report.xlsx").write_bytes(xlsx_document)
    stage = 0

    async def respond(request):
        nonlocal stage
        if stage == 0:
            stage += 1
            yield ModelChunk(
                tool_call=ToolCall(
                    "read_file",
                    {"path": "report.xlsx", "sheet": "Revenue", "cell_range": "A1:C2"},
                )
            )
            return
        replies = [
            message for message in request.messages if isinstance(message, ToolMessage)
        ]
        assert not replies[-1].is_error and "Voyager" in replies[-1].text
        assert "=B2*2" in replies[-1].text
        assert not any(
            isinstance(part, ImagePart)
            for message in request.messages
            if not isinstance(message.content, str)
            for part in message.content
        )
        yield ModelChunk(text="Workbook read as context")

    result = await Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    ).run("Read the downloaded workbook", max_steps=2)
    assert result.text == "Workbook read as context"


async def test_scoped_download_has_enum_state_and_namespaced_events(site, tmp_path):
    received = []

    async def collect(event):
        received.append(event)

    async with _receiving(Launch(url=site), LocalWorkspace(tmp_path), collect) as (
        browser,
        _,
        _,
    ):
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
        assert downloads[0].path == f"downloads/{downloads[0].id}/example.txt"
        assert (tmp_path / downloads[0].path).read_bytes() == b"download payload"
        assert any(isinstance(event, DownloadStartedEvent) for event in received)
        assert any(isinstance(event, DownloadCompletedEvent) for event in received)


async def test_default_downloads_can_be_read_and_viewed_as_pdf_in_a_new_tab(
    site, tmp_path
):
    workspace = tmp_path / "workspace"
    async with _receiving(Launch(url=site), LocalWorkspace(workspace)) as (
        browser,
        files,
        transfer,
    ):
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
        document = await files.read_file(downloaded.path, page_number=2)
        assert "Second page: Voyager 2" in document.text
        staged = await transfer.stage([downloaded.path])
        opened = await browser.tabs.open(staged.browser_paths[0])
        await wait_for_page(opened)
        assert opened.id != original.id
        assert opened.url == (workspace / downloaded.path).as_uri()
        assert await evaluate(opened, "document.contentType") == "application/pdf"
        assert original.url == site + "/"
        assert len(await browser.tabs.list()) == 2
        image = await screenshot(opened)
        assert len(image) > 1000
        (tmp_path / "pdf-preview.png").write_bytes(base64.b64decode(image))
    assert (workspace / downloaded.path).is_file()


async def test_agent_downloads_reads_previews_and_returns_to_its_original_tab(
    site, tmp_path
):
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
        replies = [
            message for message in request.messages if isinstance(message, ToolMessage)
        ]
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
            link = [
                element
                for element in page["elements"]
                if element["name"] == "Download PDF"
            ][0]
            tool_call = ToolCall("click", {"ref": link["ref"]})
        elif stage == 1:
            downloads = files["downloads"]
            if not downloads or downloads[-1]["state"] != "completed":
                yield ModelChunk(tool_call=ToolCall("list_downloads", {}))
                return
            downloaded_path = downloads[-1]["path"]
            tool_call = ToolCall(
                "read_file", {"path": downloaded_path, "page_number": 2}
            )
        elif stage == 2:
            assert "Second page: Voyager 2" in replies[-1].text
            tool_call = ToolCall(
                "open_downloaded_file", {"download_id": files["downloads"][-1]["id"]}
            )
        elif stage == 3:
            downloaded = tmp_path / "workspace" / downloaded_path
            assert page["page"]["url"] == downloaded.as_uri()
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
                "write_file",
                {"path": "notes/summary.md", "content": "Voyager 2 research"},
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
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(tmp_path / "workspace")),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run(
        "Download the PDF, inspect it and save notes", max_steps=30
    )
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
        replies = [
            message for message in request.messages if isinstance(message, ToolMessage)
        ]
        assert all(not reply.is_error for reply in replies)
        if stage == 0:
            original_tab = page["tab"]
            assert "upload_files" in {item.name for item in request.tools}
            tool_call = ToolCall("open_file", {"path": "report.pdf"})
        elif stage == 1:
            assert page["url"] == (tmp_path / "report.pdf").as_uri()
            assert page["readiness"] == "ready"
            images = [message for message in request.messages if has_image(message)]
            assert len(images) == 1
            tool_call = ToolCall("switch_tab", {"target_id": original_tab})
        else:
            assert page["tab"] == original_tab
            assert page["readiness"] == "ready"
            yield ModelChunk(text="Back on original tab")
            return
        stage += 1
        yield ModelChunk(tool_call=tool_call)

    result = await Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site + "/canvas"),
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP)
            ),
            Readiness(options=ReadinessOptions(timeout=3)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    ).run("Preview the PDF and return to the original tab", max_steps=3)
    assert result.text == "Back on original tab"


async def test_a_bridge_moves_downloads_and_uploads_between_separate_disks(
    site, tmp_path
):
    """Chrome and the workspace share no directory, as with a cloud browser."""
    workspace = LocalWorkspace(tmp_path / "workspace")
    host = tmp_path / "browser-host"
    bridge = _CopyBridge(host)
    async with _receiving(Launch(url=site, bridge=bridge), workspace) as (
        browser,
        files,
        transfer,
    ):
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            "(() => {const a=document.createElement('a');a.href='/download';"
            "a.download='example.txt';a.click();return true})()",
        )
        async with asyncio.timeout(5):
            while (
                not (downloads := await browser.downloads())
                or downloads[-1].state is not DownloadState.COMPLETED
            ):
                await asyncio.sleep(0.02)
        downloaded = downloads[-1]
        assert downloaded.error is None
        assert (await files.read_file(downloaded.path)).text == ("download payload")
        assert bridge.received[0].filename == "example.txt"
        assert not any((host / "downloads").iterdir())

        staged = await transfer.stage([downloaded.path])
        assert staged.browser_paths == (host / "uploads" / "example.txt",)
        opened = await browser.tabs.open(staged.browser_paths[0])
        await wait_for_page(opened)
        assert opened.url == (host / "uploads" / "example.txt").as_uri()
    assert (tmp_path / "workspace" / downloaded.path).is_file()


@asynccontextmanager
async def _receiving(options, workspace, emit=None):
    """Open Chrome that saves downloads into `workspace`, as `DownloadReceiving` arranges."""
    events = {} if emit is None else {"emit": emit}
    async with (
        FileSystem(workspace) as files,
        ChromeBrowser(options, **events) as browser,
    ):
        assert options.bridge is not None
        transfer = FileTransfer(files, options.bridge)
        assert await browser.receive_downloads(transfer)
        yield browser, files, transfer


class _CopyBridge:
    """Copies bytes to and from a directory only Chrome can see."""

    def __init__(self, host: Path) -> None:
        self.host = host
        self.received: list[BrowserDownload] = []

    async def download_directory(  # pylint: disable=unused-argument
        self, workspace: Workspace
    ) -> PurePath:
        (self.host / "downloads").mkdir(parents=True, exist_ok=True)
        return self.host / "downloads"

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        self.received.append(download)
        source = self.host / "downloads" / download.id
        await workspace.write_bytes(destination, source.read_bytes())
        source.unlink()

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        uploads = self.host / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        for path in paths:
            (uploads / path.name).write_bytes(await workspace.read_bytes(path))
        return [uploads / path.name for path in paths]
