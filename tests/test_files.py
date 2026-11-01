# CDP handlers are exercised directly for missing and repeated completion events.
# pylint: disable=protected-access

from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
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
    FileTransferEvent,
    FileWrittenEvent,
)
from browserrig.files import DownloadState
from browserrig.input import controller as controller_module
from browserrig.kinds import FileSource, FileTransferDirection, ReadinessPhase
from browserrig.tools import Actions, FileTools
from tests.fakes import mounted


def test_workspace_text_round_trip_pagination_and_explicit_overwrite(files):
    content = "Grüße aus dem Weltall 🌍\n" * 10
    saved = files.write_file("notes/research.md", content)
    assert saved.size == len(content.encode())
    assert files.list_files().entries[1].name == "notes"
    assert files.list_files("notes").entries[0].path == saved.path
    with pytest.raises(FileExistsError):
        files.write_file("notes/research.md", "oops")
    first = files.read_file(saved.path, max_chars=17)
    second = files.read_file(saved.path, offset=first.next_offset, max_chars=20000)
    assert first.text + second.text == content
    assert second.next_offset is None
    files.write_file(saved.path, "updated", overwrite=True)
    assert files.read_file(saved.path).text == "updated"


def test_directory_listing_is_bounded(files):
    for index in range(5):
        files.write_file(f"note-{index}.txt", "test")
    first = files.list_files(limit=2)
    second = files.list_files(offset=first.next_offset, limit=2)
    assert len(first.entries) == len(second.entries) == 2
    assert {entry.name for entry in first.entries}.isdisjoint(
        entry.name for entry in second.entries
    )


@pytest.mark.parametrize("path", ["../private.txt", "notes/../../private.txt"])
def test_workspace_rejects_traversal_for_read_write_and_list(files, path):
    for operation in (
        files.read_file,
        files.list_files,
        lambda p: files.write_file(p, "secret"),
    ):
        with pytest.raises(ValueError, match="outside"):
            operation(path)
    with pytest.raises(ValueError, match="outside"):
        files.resolve(files.directory.parent / "secret.txt")


def test_workspace_rejects_symlink_escapes(files, tmp_path):
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = files.directory / "shortcut"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="outside"):
        files.read_file("shortcut/secret.txt")
    with pytest.raises(ValueError, match="outside"):
        files.write_file("shortcut/secret.txt", "changed", overwrite=True)
    assert "shortcut" not in {entry.name for entry in files.list_files().entries}
    assert (outside / "secret.txt").read_text() == "secret"


def test_pdf_pages_and_character_continuation(files, pdf_document):
    path = files.directory / "report.pdf"
    path.write_bytes(pdf_document)
    first = files.read_file(str(path), max_chars=8)
    rest = files.read_file(str(path), page_number=1, offset=first.next_offset)
    assert "First page: Voyager 1" in first.text + rest.text
    assert first.page_count == 2
    assert first.page_number == 1
    second = files.read_file(str(path), page_number=2)
    assert "Second page: Voyager 2" in second.text
    assert "First page" not in second.text
    with pytest.raises(ValueError, match="2 pages"):
        files.read_file(str(path), page_number=3)
    with pytest.raises(ValueError, match="at least 1"):
        files.read_file(str(path), page_number=0)


def test_empty_encrypted_and_invalid_pdf_report_usable_errors(files):
    path = files.directory / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    empty = files.read_file(str(path))
    assert empty.status == "partial"
    assert any("No extractable text" in item for item in empty.limitations)
    writer.encrypt("secret")
    writer.write(path)
    with pytest.raises(ValueError, match="encrypted"):
        files.read_file(str(path))
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="Could not read PDF"):
        files.read_file(str(path))


def test_binary_missing_and_oversized_files_are_not_read_as_text(files):
    path = files.directory / "image.png"
    path.write_bytes(b"\x89PNG\x00\x01")
    with pytest.raises(OSError, match="identify image"):
        files.read_file(str(path))
    with pytest.raises(FileNotFoundError):
        files.read_file("missing.txt")
    small = FileSystem(FileSystemOptions(directory=files.directory, max_file_bytes=2))
    with pytest.raises(ValueError, match="max_file_bytes"):
        small.read_file(str(path))
    with pytest.raises(ValueError, match="max_file_bytes"):
        small.write_file("large.txt", "abc")
    files.write_file("notes.txt", "test")
    with pytest.raises(ValueError, match="only supported for PDF"):
        files.read_file("notes.txt", page_number=1)


def test_downloads_keep_extensions_and_duplicate_names_without_overwriting(
    files, pdf_document
):
    paths = []
    for download_id in ("first", "second"):
        (files.pending_directory / download_id).write_bytes(pdf_document)
        paths.append(files.complete_download(download_id, "report.pdf", None))
    assert paths[0] != paths[1]
    assert all(Path(path).name == "report.pdf" for path in paths)
    assert all(Path(path).read_bytes() == pdf_document for path in paths)
    assert len(PdfReader(BytesIO(Path(paths[0]).read_bytes())).pages) == 2


@pytest.mark.parametrize(
    "filename", ["../../report.pdf", "CON.pdf", "bad:name?.pdf", "a" * 300 + ".pdf"]
)
def test_download_names_are_safe_on_windows_and_preserve_suffix(files, filename):
    (files.pending_directory / "download-id").write_bytes(b"content")
    saved = Path(files.complete_download("download-id", filename, None))
    assert saved.is_relative_to(files.download_directory)
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == b"content"


def test_explicit_download_directory_is_accessible_without_opening_other_paths(
    tmp_path,
):
    files = FileSystem(
        FileSystemOptions(directory=tmp_path / "workspace"),
        download_directory=str(tmp_path / "downloads"),
    )
    files.initialize()
    (files.pending_directory / "id").write_text("download")
    path = files.complete_download("id", "note.txt", None)
    assert files.read_file(path).text == "download"
    with pytest.raises(ValueError, match="outside"):
        files.resolve(tmp_path / "other")


def test_uploads_resolve_workspace_and_separate_download_paths(tmp_path):
    files = FileSystem(
        FileSystemOptions(directory=tmp_path / "workspace"),
        download_directory=str(tmp_path / "downloads"),
    )
    files.initialize()
    saved = files.write_file("report.txt", "report")
    (files.pending_directory / "id").write_text("download")
    downloaded = files.complete_download("id", "note.txt", None)
    assert files.upload_paths(["report.txt", downloaded]) == [saved.path, downloaded]


def test_uploads_reject_empty_missing_directory_and_outside_paths(files, tmp_path):
    saved = files.write_file("report.txt", "report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    for path in (str(secret), "../secret.txt"):
        with pytest.raises(ValueError, match="outside"):
            files.upload_paths([saved.path, path])
    for path in ("missing.txt", "."):
        with pytest.raises(FileNotFoundError, match="existing file"):
            files.upload_paths([path])
    with pytest.raises(ValueError, match="at least one"):
        files.upload_paths([])


def test_uploads_reject_symlinks_to_outside_files(files, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    link = files.directory / "report.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError, match="outside"):
        files.upload_paths([str(link)])


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
    assert files.read_file(download.path).text == "download"
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
    saved = files.write_file("a.txt", "hello")
    listing = files.list_files()
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


async def test_open_file_moves_the_file_out_of_the_current_tab_before_reporting_it(
    files, monkeypatch
):
    sleep = AsyncMock()
    monkeypatch.setattr(controller_module.asyncio, "sleep", sleep)
    saved = files.write_file("report.txt", "report")
    opened = SimpleNamespace(id="new", document_id="new-document")
    async with _file_tools(files) as (services, tools):
        browser = services.browser
        browser.active_tab = Tab("current", SimpleNamespace(), emit=services.record)
        browser.open_tab = AsyncMock(return_value=opened)
        await tools.open_file("report.txt")
    transfer, report = (
        _first(services.events, kind) for kind in (FileTransferEvent, FileOpenedEvent)
    )
    assert transfer.target_id == "current"
    assert transfer.direction == FileTransferDirection.OPEN
    assert transfer.paths == (saved.path,)
    sleep.assert_awaited_once_with(transfer.duration)
    assert report.source == FileSource.WORKSPACE
    assert (report.target_id, report.document_id) == ("new", "new-document")
    assert report.path == saved.path
    assert services.events.index(transfer) < services.events.index(report)
    # Only the new tab is awaited; the current page is not settled afterwards.
    assert services.readiness.phases == [ReadinessPhase.NAVIGATION]


def test_remote_browser_requires_explicit_shared_filesystem(tmp_path):
    remote = Connect(endpoint="http://127.0.0.1:9222")
    assert ChromeBrowser(remote).files is None
    shared = ChromeBrowser(remote, file_system=FileSystemOptions(directory=tmp_path))
    assert shared.files.directory == tmp_path
    assert ChromeBrowser(Launch()).files is not None


async def test_io_errors_become_model_visible_tool_errors(files):
    async with _file_tools(files) as (_services, tools):
        with pytest.raises(ToolError, match="missing"):
            await tools.list_files("missing")


@pytest.fixture(name="files")
def _files(tmp_path):
    workspace = FileSystem(FileSystemOptions(directory=tmp_path / "workspace"))
    assert not workspace.directory.exists()
    workspace.initialize()
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
    files.initialize()
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
