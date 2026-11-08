import asyncio

# CDP handlers are exercised directly for missing and repeated completion events.
# pylint: disable=protected-access
from collections.abc import Sequence
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent
from harnessed import Agent, ToolError
from harnessed.testing import ScriptedModel
from pypdf import PdfReader, PdfWriter

from browserrig import (
    BrowserDownload,
    ChromeBrowser,
    FileBridge,
    FileOptions,
    Files,
    FileSystem,
    LocalWorkspace,
    MountedWorkspace,
    Workspace,
)
from browserrig.browser import Connect, Launch, Tab
from browserrig.browser import downloads as downloads_module
from browserrig.browser.downloads import Downloads
from browserrig.browser.tabs import file_url
from browserrig.events import (
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    FileOpenedEvent,
    FileReadFailedEvent,
    FileReadFinishedEvent,
    FileReadStartedEvent,
    FilesListedEvent,
    FileWrittenEvent,
)
from browserrig.files import DownloadState, FileStat, FileTransfer, workspace_path
from browserrig.files.reading import FileReader
from browserrig.kinds import FileSource, ReadinessPhase
from browserrig.tools import Actions, FileTools
from tests.fakes import mounted

_PENDING = PurePosixPath("downloads/.pending")
# Chrome on this machine reads the workspace directly.
_MOUNTED = MountedWorkspace()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", "."),
        (".", "."),
        ("notes/./a.md", "notes/a.md"),
        ("notes\\a.md", "notes/a.md"),
        ("notes/../a.md", "a.md"),
    ],
)
def test_workspace_paths_are_normalized_posix_paths(path, expected):
    assert workspace_path(path) == PurePosixPath(expected)


@pytest.mark.parametrize(
    "path", ["../a.md", "notes/../../a.md", "/etc/passwd", "C:\\secret.txt", "C:a"]
)
def test_workspace_paths_reject_absolute_and_escaping_paths(path):
    with pytest.raises(ValueError, match="outside the workspace"):
        workspace_path(path)


async def test_workspace_text_round_trip_pagination_and_explicit_overwrite(files):
    content = "Grüße aus dem Weltall 🌍\n" * 10
    # The workspace directory appears with the first file.
    assert not (await files.list_files()).entries
    assert not await files.exists("notes/research.md")
    saved = await files.write_file("notes/research.md", content)
    assert saved.path == "notes/research.md"
    assert await files.exists(saved.path)
    assert saved.size == len(content.encode())
    assert "notes" in {entry.name for entry in (await files.list_files()).entries}
    assert (await files.list_files("notes")).entries[0].path == saved.path
    with pytest.raises(FileExistsError):
        await files.write_file("notes/research.md", "oops")
    first = await files.read_file(saved.path, max_chars=17)
    assert first.path == saved.path
    second = await files.read_file(
        saved.path, offset=first.next_offset, max_chars=20000
    )
    assert first.text + second.text == content
    assert second.next_offset is None
    await files.write_file(saved.path, "updated", overwrite=True)
    assert (await files.read_file(saved.path)).text == "updated"


async def test_directory_listing_is_bounded(files):
    for index in range(5):
        await files.write_file(f"note-{index}.txt", "test")
    first = await files.list_files(limit=2)
    second = await files.list_files(offset=first.next_offset, limit=2)
    assert len(first.entries) == len(second.entries) == 2
    assert {entry.name for entry in first.entries}.isdisjoint(
        entry.name for entry in second.entries
    )


async def test_read_file_keeps_the_event_loop_responsive(files, monkeypatch):
    await files.write_file("report.txt", "threaded read")
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    read = FileReader.read

    def delayed_read(reader, *args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(timeout=5):
            raise TimeoutError("The event loop did not release the reader")
        return read(reader, *args, **kwargs)

    monkeypatch.setattr(FileReader, "read", delayed_read)
    task = asyncio.create_task(files.read_file("report.txt"))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        # The parser is still waiting, but unrelated async file work can finish.
        assert not task.done()
        assert "report.txt" in {
            entry.name for entry in (await files.list_files()).entries
        }
    finally:
        release.set()
        content = await asyncio.wait_for(task, timeout=5)
    assert content.text == "threaded read"


@pytest.mark.parametrize("path", ["../private.txt", "notes/../../private.txt"])
async def test_workspace_rejects_traversal_for_read_write_and_list(files, path):
    for operation in (
        files.exists,
        files.read_file,
        files.list_files,
        files.file,
        lambda p: files.write_file(p, "secret"),
    ):
        with pytest.raises(ValueError, match="outside"):
            await operation(path)
    with pytest.raises(ValueError, match="outside"):
        await files.read_file(str(files.workspace.directory.parent / "secret.txt"))


async def test_workspace_rejects_symlink_escapes(files, tmp_path):
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = files.workspace.directory / "shortcut"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="outside"):
        await files.read_file("shortcut/secret.txt")
    with pytest.raises(ValueError, match="outside"):
        await files.write_file("shortcut/secret.txt", "changed", overwrite=True)
    with pytest.raises(ValueError, match="outside"):
        await files.exists("shortcut/secret.txt")
    assert "shortcut" not in {
        entry.name for entry in (await files.list_files()).entries
    }
    assert (outside / "secret.txt").read_text() == "secret"


async def test_pdf_pages_and_character_continuation(files, pdf_document):
    (files.workspace.directory / "report.pdf").write_bytes(pdf_document)
    first = await files.read_file("report.pdf", max_chars=8)
    rest = await files.read_file("report.pdf", page_number=1, offset=first.next_offset)
    assert "First page: Voyager 1" in first.text + rest.text
    assert first.page_count == 2
    assert first.page_number == 1
    assert first.extracted_path.startswith(".content/")
    second = await files.read_file("report.pdf", page_number=2)
    assert "Second page: Voyager 2" in second.text
    assert "First page" not in second.text
    with pytest.raises(ValueError, match="2 pages"):
        await files.read_file("report.pdf", page_number=3)
    with pytest.raises(ValueError, match="at least 1"):
        await files.read_file("report.pdf", page_number=0)


async def test_empty_encrypted_and_invalid_pdf_report_usable_errors(files):
    path = files.workspace.directory / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    empty = await files.read_file("report.pdf")
    assert empty.status == "partial"
    assert any("No extractable text" in item for item in empty.limitations)
    writer.encrypt("secret")
    writer.write(path)
    with pytest.raises(ValueError, match="encrypted"):
        await files.read_file("report.pdf")
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="Could not read PDF"):
        await files.read_file("report.pdf")


async def test_binary_missing_and_oversized_files_are_not_read_as_text(files):
    (files.workspace.directory / "image.png").write_bytes(b"\x89PNG\x00\x01")
    with pytest.raises(OSError, match="identify image"):
        await files.read_file("image.png")
    with pytest.raises(FileNotFoundError):
        await files.read_file("missing.txt")
    small = FileSystem(files.workspace, options=FileOptions(max_file_bytes=2))
    with pytest.raises(ValueError, match="max_file_bytes"):
        await small.read_file("image.png")
    with pytest.raises(ValueError, match="max_file_bytes"):
        await small.write_file("large.txt", "abc")
    await files.write_file("notes.txt", "test")
    with pytest.raises(ValueError, match="only supported for PDF"):
        await files.read_file("notes.txt", page_number=1)


async def test_mounted_downloads_keep_extensions_and_duplicate_names(
    files, transfer, pdf_document
):
    paths = []
    for download_id in ("first", "second"):
        _pending(files, download_id).write_bytes(pdf_document)
        paths.append(await _complete(transfer, download_id, "report.pdf"))
    assert paths == ["downloads/first/report.pdf", "downloads/second/report.pdf"]
    stored = [(files.workspace.directory / path).read_bytes() for path in paths]
    assert stored == [pdf_document, pdf_document]
    assert len(PdfReader(BytesIO(stored[0])).pages) == 2
    assert not _pending(files, "first").exists()


@pytest.mark.parametrize(
    "filename", ["../../report.pdf", "CON.pdf", "bad:name?.pdf", "a" * 300 + ".pdf"]
)
async def test_download_names_are_safe_on_windows_and_preserve_suffix(
    files, transfer, filename
):
    _pending(files, "download-id").write_bytes(b"content")
    saved = PurePosixPath(await _complete(transfer, "download-id", filename))
    assert saved.parent == PurePosixPath("downloads/download-id")
    assert saved.suffix == ".pdf"
    assert (files.workspace.directory / saved).read_bytes() == b"content"


async def test_mounted_workspace_tells_chrome_the_pending_directory(files, transfer):
    directory = await transfer.download_directory()
    assert directory == files.workspace.directory / "downloads" / ".pending"
    assert (files.workspace.directory / _PENDING).is_dir()


async def test_mounted_workspace_maps_paths_onto_another_host(tmp_path):
    files = FileSystem(LocalWorkspace(tmp_path))
    transfer = FileTransfer(files, MountedWorkspace("/workspace"))
    await files.write_file("downloads/id/report.txt", "report")
    staged = await transfer.stage(["downloads/id/report.txt"])
    assert staged.paths == ("downloads/id/report.txt",)
    assert staged.browser_paths == (
        PurePosixPath("/workspace/downloads/id/report.txt"),
    )
    assert await transfer.download_directory() == PurePosixPath(
        "/workspace/downloads/.pending"
    )
    windows = MountedWorkspace("D:\\agent")
    assert windows.browser_path == PureWindowsPath("D:/agent")
    with pytest.raises(ValueError, match="absolute"):
        MountedWorkspace("workspace")


@pytest.mark.parametrize(
    ("path", "url"),
    [
        (PurePosixPath("/workspace/a b/r.pdf"), "file:///workspace/a%20b/r.pdf"),
        (PureWindowsPath("C:/Users/a b/r.pdf"), "file:///C:/Users/a%20b/r.pdf"),
        (PureWindowsPath("//server/share/r.pdf"), "file://server/share/r.pdf"),
    ],
)
def test_browser_host_paths_open_as_file_urls_of_the_host_os(path, url):
    assert file_url(path) == url


async def test_stage_validates_the_whole_selection_and_returns_host_paths(
    files, transfer
):
    saved = await files.write_file("report.txt", "report")
    _pending(files, "id").write_text("download")
    downloaded = await _complete(transfer, "id", "note.txt")
    staged = await transfer.stage(["report.txt", downloaded])
    assert staged.paths == (saved.path, downloaded)
    assert staged.browser_paths == (
        files.workspace.directory / "report.txt",
        files.workspace.directory / "downloads/id/note.txt",
    )


async def test_stage_rejects_empty_missing_directory_and_outside_paths(
    files, transfer, tmp_path
):
    saved = await files.write_file("report.txt", "report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    for path in (str(secret), "../secret.txt"):
        with pytest.raises(ValueError, match="outside"):
            await transfer.stage([saved.path, path])
    for path in ("missing.txt", "."):
        with pytest.raises(FileNotFoundError, match="File not found"):
            await transfer.stage([path])
    with pytest.raises(ValueError, match="at least one"):
        await transfer.stage([])


async def test_stage_rejects_symlinks_to_outside_files(files, transfer, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    link = files.workspace.directory / "report.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="outside"):
        await transfer.stage(["report.txt"])


async def test_workspace_without_a_bridge_keeps_files_but_cannot_reach_chrome(files):
    await files.write_file("report.txt", "report")
    async with _file_tools(files, bridge=None) as (services, tools):
        assert services.browser.receiving is None
        await tools.read_file("report.txt")
        with pytest.raises(ToolError, match="file bridge"):
            await tools.open_file("report.txt")
    assert _first(services.events, FileReadFinishedEvent).path == "report.txt"


async def test_remote_workspace_and_cloud_bridge_handle_reads_downloads_and_uploads(
    pdf_document,
):
    workspace = _MemoryWorkspace()
    bridge = _CloudBridge()
    assert isinstance(workspace, Workspace) and isinstance(bridge, FileBridge)
    async with FileSystem(workspace) as files:
        assert workspace.open
        transfer = FileTransfer(files, bridge)
        assert await transfer.download_directory() == PurePosixPath("/cloud/downloads")
        bridge.remote["dl-1"] = pdf_document
        path = await transfer.receive(
            "dl-1", "report.pdf", "https://example.org/report.pdf", None
        )
        assert path == "downloads/dl-1/report.pdf"
        assert workspace.files[PurePosixPath(path)] == pdf_document
        assert bridge.received[0].url == "https://example.org/report.pdf"

        # Remote files are parsed from a local copy; the extraction stays local.
        document = await files.read_file(path, page_number=2)
        assert "Second page: Voyager 2" in document.text
        assert document.path == path and document.extracted_path is None
        assert len(workspace.reads) == 1
        await files.read_file(path, page_number=1)
        assert len(workspace.reads) == 1

        staged = await transfer.stage([path])
        assert staged.browser_paths == (PurePosixPath("/cloud/uploads/report.pdf"),)
        assert bridge.uploaded == {"report.pdf": pdf_document}

        listing = await files.list_files("downloads/dl-1")
        assert [entry.path for entry in listing.entries] == [path]
        # Only a workspace on this machine can be mounted for Chrome.
        with pytest.raises(ValueError, match="LocalWorkspace"):
            await FileTransfer(files, MountedWorkspace("/w")).download_directory()
    assert not workspace.open


async def test_remote_reads_respect_the_size_limit_before_copying():
    workspace = _MemoryWorkspace()
    files = FileSystem(workspace, options=FileOptions(max_file_bytes=4))
    await workspace.write_bytes(PurePosixPath("large.txt"), b"too large")
    with pytest.raises(ValueError, match="max_file_bytes"):
        await files.read_file("large.txt")
    assert not workspace.reads


_COMPLETED = DownloadProgressEvent(
    guid="id", total_bytes=8, received_bytes=8, state="completed"
)


async def test_download_completion_falls_back_to_guid_and_tolerates_repeated_events(
    tmp_path,
):
    files, downloads, emit = await _started_download(tmp_path)
    _pending(files, "id").write_text("download")
    await downloads.handle(_COMPLETED)
    await downloads.handle(_COMPLETED)
    (download,) = downloads.all()
    assert download.state is DownloadState.COMPLETED
    assert download.path == "downloads/id/note.txt"
    assert (await files.read_file(download.path)).text == "download"
    assert download.error is None
    completed = [call.args[0] for call in emit.await_args_list]
    assert [type(event) for event in completed].count(DownloadCompletedEvent) == 1


async def test_missing_download_fails_without_raising(tmp_path):
    _, downloads, emit = await _started_download(tmp_path)
    await downloads.handle(_COMPLETED)
    (download,) = downloads.all()
    assert download.path is None
    assert "could not be saved" in download.error
    assert isinstance(emit.await_args.args[0], DownloadFailedEvent)


async def test_a_failing_bridge_ends_the_download_as_failed(tmp_path):
    class _Broken(MountedWorkspace):
        async def receive(self, workspace, download, destination):
            raise RuntimeError("provider unavailable")

    _, downloads, emit = await _started_download(tmp_path, _Broken())
    await downloads.handle(_COMPLETED)
    (download,) = downloads.all()
    assert download.state is DownloadState.COMPLETED and download.path is None
    assert "provider unavailable" in download.error
    assert isinstance(emit.await_args.args[0], DownloadFailedEvent)


async def test_downloads_are_not_received_unless_chrome_saves_them_for_the_bridge(
    tmp_path,
):
    _, downloads, emit = await _started_download(tmp_path, None)
    await downloads.handle(_COMPLETED)
    (download,) = downloads.all()
    assert download.state is DownloadState.COMPLETED
    assert download.path is None and download.error is None
    assert isinstance(emit.await_args.args[0], DownloadCompletedEvent)


async def test_download_progress_is_throttled_and_cancel_is_not_a_failure(
    tmp_path, monkeypatch
):
    clock = iter([10.0, 10.05, 10.3])
    monkeypatch.setattr(downloads_module, "monotonic", lambda: next(clock))
    _, downloads, emit = await _started_download(tmp_path)
    for received in (2, 4, 6):
        await downloads.handle(_progress(received, "inProgress"))
    await downloads.handle(_progress(6, "canceled"))
    emitted = [call.args[0] for call in emit.await_args_list]
    progress = [
        event for event in emitted if isinstance(event, DownloadProgressedEvent)
    ]
    assert [(event.received_bytes, event.total_bytes) for event in progress] == [
        (2, 8),
        (6, 8),
    ]
    assert isinstance(emitted[-1], DownloadCanceledEvent)
    assert not any(isinstance(event, DownloadFailedEvent) for event in emitted)
    (download,) = downloads.all()
    assert download.state is DownloadState.CANCELED and download.total_bytes == 8


async def test_download_progress_without_a_known_size_reports_no_total(tmp_path):
    _, downloads, emit = await _started_download(tmp_path)
    await downloads.handle(_progress(3, "inProgress", total=0))
    assert emit.await_args.args[0].total_bytes is None
    assert downloads.all()[0].received_bytes == 3


async def test_file_tools_report_listing_reads_and_writes(files):
    saved = await files.write_file("a.txt", "hello")
    listing = await files.list_files()
    async with _file_tools(files) as (services, tools):
        await tools.list_files()
        await tools.read_file("a.txt")
        with pytest.raises(ToolError):
            await tools.read_file("missing.txt")
        await tools.write_file("b.txt", "new")
        await tools.write_file("b.txt", "again", overwrite=True)
    listed, started, finished, missing, failed, created, replaced = services.events
    assert isinstance(listed, FilesListedEvent)
    assert listed.entries == len(listing.entries)
    assert isinstance(started, FileReadStartedEvent) and started.path == "a.txt"
    assert (
        isinstance(finished, FileReadFinishedEvent)
        and finished.read_id == started.read_id
    )
    assert finished.path == saved.path and finished.characters == 5
    assert isinstance(missing, FileReadStartedEvent)
    assert isinstance(failed, FileReadFailedEvent) and failed.read_id == missing.read_id
    assert missing.read_id != started.read_id
    assert (
        isinstance(created, FileWrittenEvent) and created.created and created.size == 3
    )
    assert isinstance(replaced, FileWrittenEvent) and not replaced.created


async def test_open_file_reports_the_file_in_its_new_tab(files, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    saved = await files.write_file("report.txt", "report")
    opened = SimpleNamespace(id="new", document_id="new-document")
    async with _file_tools(files) as (services, tools):
        browser = services.browser
        browser.active_tab = Tab("current", SimpleNamespace(), emit=services.record)
        browser.tabs.open = AsyncMock(return_value=opened)
        await tools.open_file("report.txt")
    browser.tabs.open.assert_awaited_once_with(files.workspace.directory / "report.txt")
    report = _first(services.events, FileOpenedEvent)
    # Nobody watches, so nothing is staged and nothing pauses.
    sleep.assert_not_awaited()
    assert report.source == FileSource.WORKSPACE
    assert (report.target_id, report.document_id) == ("new", "new-document")
    assert report.path == saved.path
    # Only the new tab is awaited; the current page is not settled afterwards.
    assert services.readiness.phases == [ReadinessPhase.NAVIGATION]


async def test_browsers_choose_the_bridge_and_files_choose_the_workspace(tmp_path):
    endpoint = "http://127.0.0.1:9222"
    assert ChromeBrowser(Connect(endpoint=endpoint)).bridge is None
    bridge = MountedWorkspace("/workspace")
    assert ChromeBrowser(Connect(endpoint=endpoint, bridge=bridge)).bridge is bridge
    assert isinstance(ChromeBrowser(Launch()).bridge, MountedWorkspace)

    workspace = LocalWorkspace(tmp_path)
    async with mounted(Files(workspace)) as (_services, ctx):
        assert ctx[FileSystem].workspace is workspace
    # Without a workspace, each session gets its own.
    agent = Agent(model=ScriptedModel(["Done", "Done"]), plugins=[Files()])
    directories = []
    for _ in range(2):
        async with agent.session() as session:
            directories.append(session.scope[FileSystem].workspace.directory)
    assert directories[0] != directories[1]


async def test_io_errors_become_model_visible_tool_errors(files):
    async with _file_tools(files) as (_services, tools):
        with pytest.raises(ToolError, match="missing"):
            await tools.list_files("missing")


@pytest.mark.parametrize("path", ["missing.txt", "notes"])
async def test_open_file_requires_an_existing_regular_file(files, path):
    (files.workspace.directory / "notes").mkdir()
    async with _file_tools(files) as (_services, tools):
        with pytest.raises(ToolError, match="File not found"):
            await tools.open_file(path)


async def test_cancelled_read_reports_failure_and_propagates_cancellation(
    files, monkeypatch
):
    read = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(files, "read_file", read)
    async with _file_tools(files) as (services, tools):
        with pytest.raises(asyncio.CancelledError):
            await tools.read_file("report.txt")
    read.assert_awaited_once()
    started, failed = services.events
    assert isinstance(started, FileReadStartedEvent)
    assert isinstance(failed, FileReadFailedEvent)
    assert failed.read_id == started.read_id and failed.reason == "Read cancelled"


@pytest.fixture(name="files")
async def _files(tmp_path):
    files = FileSystem(LocalWorkspace(tmp_path / "workspace"))
    assert not files.workspace.directory.exists()
    # Applications put files here directly, as well as through the tools.
    files.workspace.directory.mkdir()
    return files


@pytest.fixture(name="transfer")
async def _transfer(files):
    transfer = FileTransfer(files, MountedWorkspace())
    await transfer.download_directory()
    return transfer


class _MemoryWorkspace:
    """A workspace that lives elsewhere, such as on a pod or in a bucket."""

    def __init__(self) -> None:
        self.files: dict[PurePosixPath, bytes] = {}
        self.reads: list[PurePosixPath] = []
        self.open = False

    async def __aenter__(self) -> "_MemoryWorkspace":
        self.open = True
        return self

    async def __aexit__(self, *_exception) -> None:
        self.open = False

    async def stat(self, path: PurePosixPath) -> FileStat | None:
        if path in self.files:
            return FileStat(path, False, len(self.files[path]), 1.0)
        if any(path in item.parents for item in self.files):
            return FileStat(path, True, None, 1.0)
        return None

    async def list(self, path: PurePosixPath) -> Sequence[FileStat]:
        children = {
            path / item.relative_to(path).parts[0]
            for item in self.files
            if path in item.parents
        }
        return [await self.stat(child) for child in children]

    async def read_bytes(self, path: PurePosixPath) -> bytes:
        self.reads.append(path)
        return self.files[path]

    async def write_bytes(self, path: PurePosixPath, data: bytes) -> None:
        self.files[path] = data


class _CloudBridge:
    """A cloud browser provider's file API, reached without a shared disk."""

    def __init__(self) -> None:
        self.remote: dict[str, bytes] = {}
        self.received: list[BrowserDownload] = []
        self.uploaded: dict[str, bytes] = {}

    async def download_directory(  # pylint: disable=unused-argument
        self, workspace: Workspace
    ) -> PurePath:
        return PurePosixPath("/cloud/downloads")

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        self.received.append(download)
        await workspace.write_bytes(destination, self.remote[download.id])

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        for path in paths:
            self.uploaded[path.name] = await workspace.read_bytes(path)
        return [PurePosixPath("/cloud/uploads") / path.name for path in paths]


def _pending(files, download_id):
    return files.workspace.directory / _PENDING / download_id


async def _complete(transfer, download_id, filename):
    return await transfer.receive(download_id, filename, "https://example.org", None)


def _progress(received, state, total=8):
    return DownloadProgressEvent(
        guid="id", total_bytes=total, received_bytes=received, state=state
    )


class _FileTools(FileTools, provides=True):
    """Expose the mounted plugin, so tests can call its tools directly."""


@asynccontextmanager
async def _file_tools(files, bridge=_MOUNTED):
    plugins = (Actions(), _FileTools())
    async with mounted(*plugins, bridge=bridge, files=files) as (services, ctx):
        yield services, ctx[_FileTools]


def _first(events, kind):
    return next(event for event in events if isinstance(event, kind))


async def _started_download(tmp_path, bridge=_MOUNTED):
    files = FileSystem(LocalWorkspace(tmp_path))
    transfer = FileTransfer(files, bridge) if bridge is not None else None
    emit = AsyncMock()
    downloads = Downloads(emit=emit)
    cdp = SimpleNamespace(browser=SimpleNamespace(set_download_behavior=AsyncMock()))
    receiving = await downloads.receive(cdp, "context", transfer)
    assert receiving is (transfer is not None)
    await downloads.handle(
        DownloadWillBeginEvent(
            frame_id="frame",
            guid="id",
            url="https://example.org",
            suggested_filename="note.txt",
        )
    )
    return files, downloads, emit
