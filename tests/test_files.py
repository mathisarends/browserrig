import asyncio

# CDP handlers are exercised directly for missing and repeated completion events.
# pylint: disable=protected-access
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent
from harnessed import ToolError
from pypdf import PdfReader, PdfWriter

from browserrig import (
    ChromeBrowser,
    Connect,
    FileSystem,
    FileSystemOptions,
    Launch,
)
from browserrig.browser import Tab
from browserrig.browser import downloads as downloads_module
from browserrig.browser.downloads import Downloads
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
from browserrig.files import DownloadState
from browserrig.files.reading import FileReader
from browserrig.kinds import FileSource, ReadinessPhase
from browserrig.tools import Actions, FileTools
from tests.fakes import mounted


async def test_workspace_text_round_trip_pagination_and_explicit_overwrite(files):
    content = "Grüße aus dem Weltall 🌍\n" * 10
    assert not await files.exists("notes/research.md")
    saved = await files.write_file("notes/research.md", content)
    assert await files.exists(saved.path)
    assert await files.resolve(saved.path, require_file=True) == Path(saved.path)
    assert saved.size == len(content.encode())
    assert (await files.list_files()).entries[1].name == "notes"
    assert (await files.list_files("notes")).entries[0].path == saved.path
    with pytest.raises(FileExistsError):
        await files.write_file("notes/research.md", "oops")
    first = await files.read_file(saved.path, max_chars=17)
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
        assert (await files.list_files()).entries[1].name == "report.txt"
    finally:
        release.set()
        content = await asyncio.wait_for(task, timeout=5)
    assert content.text == "threaded read"


@pytest.mark.parametrize("path", ["../private.txt", "notes/../../private.txt"])
async def test_workspace_rejects_traversal_for_read_write_and_list(files, path):
    for operation in (
        files.resolve,
        files.exists,
        files.read_file,
        files.list_files,
        lambda p: files.write_file(p, "secret"),
    ):
        with pytest.raises(ValueError, match="outside"):
            await operation(path)
    with pytest.raises(ValueError, match="outside"):
        await files.resolve(files.directory.parent / "secret.txt")


async def test_workspace_rejects_symlink_escapes(files, tmp_path):
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = files.directory / "shortcut"
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
    path = files.directory / "report.pdf"
    path.write_bytes(pdf_document)
    first = await files.read_file(str(path), max_chars=8)
    rest = await files.read_file(str(path), page_number=1, offset=first.next_offset)
    assert "First page: Voyager 1" in first.text + rest.text
    assert first.page_count == 2
    assert first.page_number == 1
    second = await files.read_file(str(path), page_number=2)
    assert "Second page: Voyager 2" in second.text
    assert "First page" not in second.text
    with pytest.raises(ValueError, match="2 pages"):
        await files.read_file(str(path), page_number=3)
    with pytest.raises(ValueError, match="at least 1"):
        await files.read_file(str(path), page_number=0)


async def test_empty_encrypted_and_invalid_pdf_report_usable_errors(files):
    path = files.directory / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    empty = await files.read_file(str(path))
    assert empty.status == "partial"
    assert any("No extractable text" in item for item in empty.limitations)
    writer.encrypt("secret")
    writer.write(path)
    with pytest.raises(ValueError, match="encrypted"):
        await files.read_file(str(path))
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="Could not read PDF"):
        await files.read_file(str(path))


async def test_binary_missing_and_oversized_files_are_not_read_as_text(files):
    path = files.directory / "image.png"
    path.write_bytes(b"\x89PNG\x00\x01")
    with pytest.raises(OSError, match="identify image"):
        await files.read_file(str(path))
    with pytest.raises(FileNotFoundError):
        await files.read_file("missing.txt")
    small = FileSystem(FileSystemOptions(directory=files.directory, max_file_bytes=2))
    with pytest.raises(ValueError, match="max_file_bytes"):
        await small.read_file(str(path))
    with pytest.raises(ValueError, match="max_file_bytes"):
        await small.write_file("large.txt", "abc")
    await files.write_file("notes.txt", "test")
    with pytest.raises(ValueError, match="only supported for PDF"):
        await files.read_file("notes.txt", page_number=1)


async def test_downloads_keep_extensions_and_duplicate_names_without_overwriting(
    files, pdf_document
):
    paths = []
    for download_id in ("first", "second"):
        (files.pending_directory / download_id).write_bytes(pdf_document)
        paths.append(await files.complete_download(download_id, "report.pdf", None))
    assert paths[0] != paths[1]
    assert all(Path(path).name == "report.pdf" for path in paths)
    assert all(Path(path).read_bytes() == pdf_document for path in paths)
    assert len(PdfReader(BytesIO(Path(paths[0]).read_bytes())).pages) == 2


@pytest.mark.parametrize(
    "filename", ["../../report.pdf", "CON.pdf", "bad:name?.pdf", "a" * 300 + ".pdf"]
)
async def test_download_names_are_safe_on_windows_and_preserve_suffix(files, filename):
    (files.pending_directory / "download-id").write_bytes(b"content")
    saved = Path(await files.complete_download("download-id", filename, None))
    assert saved.is_relative_to(files.download_directory)
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == b"content"


async def test_explicit_download_directory_is_accessible_without_opening_other_paths(
    tmp_path,
):
    files = FileSystem(
        FileSystemOptions(directory=tmp_path / "workspace"),
        download_directory=str(tmp_path / "downloads"),
    )
    await files.initialize()
    (files.pending_directory / "id").write_text("download")
    path = await files.complete_download("id", "note.txt", None)
    assert (await files.read_file(path)).text == "download"
    with pytest.raises(ValueError, match="outside"):
        await files.resolve(tmp_path / "other")


async def test_uploads_resolve_workspace_and_separate_download_paths(tmp_path):
    files = FileSystem(
        FileSystemOptions(directory=tmp_path / "workspace"),
        download_directory=str(tmp_path / "downloads"),
    )
    await files.initialize()
    saved = await files.write_file("report.txt", "report")
    (files.pending_directory / "id").write_text("download")
    downloaded = await files.complete_download("id", "note.txt", None)
    assert await files.upload_paths(["report.txt", downloaded]) == [
        saved.path,
        downloaded,
    ]


async def test_uploads_reject_empty_missing_directory_and_outside_paths(
    files, tmp_path
):
    saved = await files.write_file("report.txt", "report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    for path in (str(secret), "../secret.txt"):
        with pytest.raises(ValueError, match="outside"):
            await files.upload_paths([saved.path, path])
    for path in ("missing.txt", "."):
        with pytest.raises(FileNotFoundError, match="existing file"):
            await files.upload_paths([path])
    with pytest.raises(ValueError, match="at least one"):
        await files.upload_paths([])


async def test_uploads_reject_symlinks_to_outside_files(files, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    link = files.directory / "report.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="outside"):
        await files.upload_paths([str(link)])


_COMPLETED = DownloadProgressEvent(
    guid="id", total_bytes=8, received_bytes=8, state="completed"
)


async def test_download_completion_falls_back_to_guid_and_tolerates_repeated_events(
    tmp_path,
):
    files, downloads, emit = await _started_download(tmp_path)
    (files.pending_directory / "id").write_text("download")
    await downloads.handle(_COMPLETED)
    await downloads.handle(_COMPLETED)
    (download,) = downloads.all()
    assert download.state is DownloadState.COMPLETED
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
        browser.open_tab = AsyncMock(return_value=opened)
        await tools.open_file("report.txt")
    report = _first(services.events, FileOpenedEvent)
    # Nobody watches, so nothing is staged and nothing pauses.
    sleep.assert_not_awaited()
    assert report.source == FileSource.WORKSPACE
    assert (report.target_id, report.document_id) == ("new", "new-document")
    assert report.path == saved.path
    # Only the new tab is awaited; the current page is not settled afterwards.
    assert services.readiness.phases == [ReadinessPhase.NAVIGATION]


def test_remote_browser_requires_explicit_shared_filesystem(tmp_path):
    endpoint = "http://127.0.0.1:9222"
    assert ChromeBrowser(Connect(endpoint=endpoint)).files is None
    shared = ChromeBrowser(
        Connect(endpoint=endpoint, files=FileSystemOptions(directory=tmp_path))
    )
    assert shared.files.directory == tmp_path
    assert ChromeBrowser(Launch()).files is not None


async def test_io_errors_become_model_visible_tool_errors(files):
    async with _file_tools(files) as (_services, tools):
        with pytest.raises(ToolError, match="missing"):
            await tools.list_files("missing")


@pytest.mark.parametrize("path", ["missing.txt", "downloads"])
async def test_open_file_requires_an_existing_regular_file(files, path):
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
    workspace = FileSystem(FileSystemOptions(directory=tmp_path / "workspace"))
    assert not workspace.directory.exists()
    await workspace.initialize()
    return workspace


def _progress(received, state, total=8):
    return DownloadProgressEvent(
        guid="id", total_bytes=total, received_bytes=received, state=state
    )


class _FileTools(FileTools, provides=True):
    """Expose the mounted plugin, so tests can call its tools directly."""


@asynccontextmanager
async def _file_tools(files):
    async with mounted(Actions(), _FileTools()) as (services, ctx):
        services.browser.files = files
        yield services, ctx[_FileTools]


def _first(events, kind):
    return next(event for event in events if isinstance(event, kind))


async def _started_download(tmp_path):
    files = FileSystem(FileSystemOptions(directory=tmp_path))
    await files.initialize()
    emit = AsyncMock()
    downloads = Downloads(files=files, directory=None, emit=emit)
    await downloads.handle(
        DownloadWillBeginEvent(
            frame_id="frame",
            guid="id",
            url="https://example.org",
            suggested_filename="note.txt",
        )
    )
    return files, downloads, emit
