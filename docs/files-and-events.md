# Files and events

[Back to README](../README.md)

```mermaid
flowchart LR
    Chrome --> Downloads
    Downloads --> Workspace
    Workspace --> FileTools[File tools]
    FileTools --> Agent
    Agent --> Events
    Chrome --> Events
```

## Visual file reads

The existing `read_file` tool accepts `view="auto"` (default), `"text"`, or
`"image"`. Auto shows image files as visual model content and reads other formats
as text. Select `view="image", page_number=12` to inspect a PDF page, or select an
image frame with the same `page_number` selector. Visual reads run no OCR, preserve
the source, and return a PNG preview bounded to 2048 pixels on its longest edge.
PDF rendering requires `pypdfium2`, included in `browserrig[files]`; image previews
need only the base installation. The selected model must support image inputs.

Use `view="text"` for image OCR. Direct Python `FileSystem.read_file` calls retain
their default text view; they expose a visual read as `FileContent.image` when
explicitly requested. The model tool delivers that field as an image content part,
without embedding Base64 data in its text response. `open_file` still opens a
browser preview independently.

Finish the current selection using `next_offset` before moving to
`next_page_number` or `next_sheet`. These continuation fields are supplied only
after the current text selection ends; pass the same view and other selectors.

## Downloads and events

Completed downloads automatically retain the original and create adjacent
`<filename>.md` and `<filename>.extraction.json` files. Indexing runs in the
background; `list_downloads` includes the extraction path, processing status,
indexed pages, pending OCR pages and any error independently of download status.
The file system waits for its indexing jobs before closing the workspace.

PDFs are scanned once for native text across all pages, within `max_file_bytes`,
`max_expanded_bytes` and `max_index_pages` (default 2,000). Up to
`auto_ocr_pages` (default 3) pages without native text then use local OCR when it
is enabled and installed. Set this budget to 0 to defer automatic OCR entirely,
or set `auto_extract=False` to disable automatic sidecars. The page budget limits
automatic work, not latency; OCR time depends on page resolution and hardware.

Workbook indexing visits all sheets while retaining the readers' explicit limits
for large/sparse ranges. Unsupported formats and failed conversions remain
inspectable beside the raw file. Searchable text is not a complete interpretation
of drawings, images, charts or document annotations.

An explicit `read_file` of an indexed source adds its full selected page/sheet to
the sidecar, regardless of `max_chars`. Use `page_number` and `ocr=True` to recognize
pending PDF pages on demand; the per-page cache avoids repeating unchanged OCR.
The returned `document_path` names the sidecar; `extracted_path` continues to name
the complete selected extraction. Source changes invalidate the document index.
Unmanaged Markdown files are never overwritten. Internal index chunks stay under
`.content/index/` and the adjacent Markdown is the canonical search surface.

The agent works in one **workspace**. Downloads land in its `downloads/` folder,
so everything the agent can read, write, open or upload has a workspace-relative
path such as `downloads/<id>/report.pdf` or `notes/summary.md`.

## Saved webpage extractions

With `Files()` configured, each `extract_content(full_page=False)` call writes a
new snapshot to `pages/<unique-id>/content.md`. Adjacent `source.json` records the
URL, title, capture time, extraction mode and reported limitations. The agent sees
only a receipt, without the page body or a generated summary:

```text
Saved: pages/<unique-id>/content.md
Source: https://example.org/report
Title: Report
```

Actual extraction limitations follow the receipt when present. The tool infers no
semantic contents or completeness claims. Use `grep(query, pattern=<saved-path>)`
to find bounded matches and `read_file(path, offset=..., max_chars=4000)` to inspect
an excerpt. The snapshot remains readable after navigating elsewhere; a later
extraction saves a separate file. Agent-tool `max_chars` and `offset` parameters
are removed: reading and pagination belong to the file tools.

The snapshot covers loaded, extractable content and is bounded to 2,000,000
characters plus DOM traversal limits. Missing or truncated content is reported.
The agent tool is unavailable without a workspace and never falls back to inline
page text. Configured secret values are redacted before persistence. The direct
Python helper `browserrig.observation.content.extract_content(tab, ...)` still
returns Markdown and supports `max_chars`/`offset` without requiring a workspace.

`glob(pattern="**/*", limit=200)` finds workspace files. `grep(query,
pattern="**/*.md", limit=20)` searches literal text case-insensitively and returns
bounded `path:line` snippets with Unicode character offsets for `read_file`.
Search reads complete UTF-8 files, including text beyond file-preview limits.
Hidden directories and internal caches are excluded unless `include_hidden=True`.
File counts, scanned bytes, directory walks and match counts are bounded; skipped
files, partial extractions and incomplete searches are reported. At most 20 notes
are returned, with an omitted count when needed. A limited search is not evidence
that the requested text is absent.

The default recipe's `Files` plugin gives each session a local workspace under
`.browserrig/files/<unique-id>/`. Files remain available after the session ends.
Choose a reusable workspace explicitly:

```python
from browserrig import Agent, Chrome, FileOptions, Files, LocalWorkspace

agent = Agent(
    model=model,
    browser=Chrome.launch(url="https://example.com"),
    plugins=[
        Files(
            LocalWorkspace(".browserrig/research"),
            options=FileOptions(max_file_bytes=20_000_000),
        )
    ],
)
```

The workspace belongs to the agent, not to the browser: `Files` opens it as the
session's `FileSystem` service. The browser only decides, through its `bridge`,
whether Chrome can save downloads into it and read from it. Constructors create
no files or directories; the workspace directory appears with the first file.
File tools only accept workspace-relative paths; absolute paths, `..` traversal
and symlinks leaving the workspace are rejected.

The agent sees the workspace and its latest 20 downloads before every step.
File tools are available alongside the browser tools:

`WorkspaceTools()` contains list/read/write and can run without a browser; with
one, it shows the same file system observation, so new downloads stay visible.
`BrowserFileTools()` contains download listing, previews and uploads.
The default `FileTools()` combines both groups. All three share one slot: pass
`WorkspaceTools()` or `BrowserFileTools()` in `plugins` to replace the default
with only that group.
`DownloadReceiving()` independently binds browser downloads to the workspace;
removing tools does not stop download receiving.

| Tool                                                                                                               | Behavior                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_files(path=".", offset=0, limit=100)`                                                                        | List a directory; follow `next_offset` for more.                                                                                                              |
| `read_file(path, page_number=None, sheet=None, cell_range=None, member=None, ocr=None, offset=0, max_chars=20000)` | Read native document content, worksheet cells, archive members or OCR text. Returns structure, limitations, a saved extraction path and continuation offsets. |
| `write_file(path, content, overwrite=False, append=False)`                                                         | Save UTF-8 text and create parent directories; overwriting requires an explicit flag. `append=True` adds to the end and creates a missing file.               |
| `edit_file(path, old_text, new_text, replace_all=False)`                                                           | Replace exact text in a UTF-8 file. `old_text` must match once unless `replace_all=True`.                                                                     |
| `list_downloads()`                                                                                                 | List download IDs, status, saved paths, and file errors.                                                                                                      |
| `open_downloaded_file(download_id)`                                                                                | Open a completed download in a new active tab.                                                                                                                |
| `open_file(path)`                                                                                                  | Open a workspace/download file in a new active tab.                                                                                                           |

Pass paths returned by `list_files` or `list_downloads`, or paths relative to the
workspace. Without extras, `read_file` reads plain text. Install
`browserrig[files]` for the document, spreadsheet, PDF and media readers below, or
`browserrig[ocr]` for those readers plus local CPU OCR. When a reader is missing,
`read_file` names the extra to install; text-based formats such as CSV or HTML
fall back to their raw text with status `partial`. Without OCR, images return
metadata only and scanned PDF pages report that OCR is not installed.

| Format                                                        | Content and selection                                                                                                                                                                                   |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Text, Markdown, source code, JSON, XML, YAML, logs, subtitles | Text with encoding detection and character offsets.                                                                                                                                                     |
| CSV, TSV; XLSX/XLSM/XLTX/XLTM, XLS, ODS                       | Worksheet names and cell addresses; choose `sheet` and an A1 `cell_range`. XLSX includes formulas, stored results, number formats, merged and hidden ranges.                                            |
| PDF                                                           | One page, defaulting to page 1; `page_count` exposes the remaining pages. Pages without native text use local OCR automatically. `ocr=True` explicitly requests full-page OCR; `ocr=False` disables it. |
| PNG, JPEG, TIFF, GIF, BMP, WEBP, ICO                          | Image metadata and local OCR text; `page_number` selects a frame in a multi-frame image.                                                                                                                |
| DOCX, PPTX, ODT, ODP, RTF                                     | Document text and tables; PPTX also exposes speaker notes and optional slide selection with `page_number`.                                                                                              |
| HTML/XHTML/SVG, MHTML, EPUB                                   | Readable text; EPUB follows chapter order. Embedded images and document-specific resources have explicit limitations.                                                                                   |
| ZIP, TAR and compressed TAR; GZ, BZ2, XZ; EML, MBOX           | Entry or attachment listings. Select `member="report.xlsx"`, `member="#1"`, or nested `member="bundle.zip!/report.xlsx"`; the same readers process the selected content.                                |
| SQLite                                                        | Table names and values; select a table with `sheet`. Binary BLOBs are identified by size.                                                                                                               |
| Audio and video                                               | Metadata only; no transcription or video understanding.                                                                                                                                                 |

`max_chars` limits each response, independently of the saved extraction. Converted
content is saved under the workspace's `.content/` directory and returned as
`extracted_path`. It contains the full selected page, sheet, range, member or
document, including extraction limitations. Follow `next_offset` with the same
selection to continue, or read `extracted_path` as text. Plain text streams directly
from the original file. Changing the source invalidates its derived cache.

`status` distinguishes `complete`, `partial`, `metadata_only` and `unsupported`;
`limitations` identifies missing content. Office graphics, comments and annotations
are not fully represented. OCR can make recognition and reading-order errors.
Formulas are never recalculated and stored results may be stale. Source files
are preserved; macros and scripts are not executed. Legacy DOC/PPT, XLSB, MSG,
7Z/RAR, iWork, MOBI/AZW and specialized binary datasets currently report missing
reader support explicitly.

`max_file_bytes` defaults to 50 MB for document parser inputs and writes; plain
text reads stream beyond that size. `max_expanded_bytes` defaults to 200 MB and
covers both expanded document inputs and the UTF-8 extraction saved to the cache.
`max_archive_depth` defaults to 8. Exceeding a processing bound raises an explicit error.
Very large or sparse XLSX sheets expose a bounded initial view with a limitation
and support targeted `cell_range` reads elsewhere in the sheet. These processing
bounds are separate from response pagination.

`FileTools` includes workspace operations, downloads and `upload_files`.
Omit `Files` and `FileTools` with `without=(Files, FileTools)` to remove the entire
file capability; `without=(Files,)` leaves only `list_downloads`.

File tools report facts as durable `browser.files.*` events, registered by
`FileTools` (`FILE_EVENTS` and `UPLOAD_EVENTS`). Presentation,
such as a file drawer, is left to the viewer:

| Event                   | Emitted by                          | Payload                                                             |
| ----------------------- | ----------------------------------- | ------------------------------------------------------------------- |
| `FilesListedEvent`      | `list_files`                        | Directory, entry count and pagination offsets                       |
| `FileReadStartedEvent`  | `read_file`                         | `read_id`, requested path and selectors                             |
| `FileReadFinishedEvent` | `read_file`                         | `read_id`, path, format, status, character count, pages and offsets |
| `FileReadFailedEvent`   | `read_file`                         | `read_id`, requested path and reason, including cancellation        |
| `FileWrittenEvent`      | `write_file`, `edit_file`           | Path, size and whether the file was created                         |
| `FileOpenedEvent`       | `open_file`, `open_downloaded_file` | Path, `FileSource` and download ID; `target_id` is the new tab      |
| `FilesUploadedEvent`    | `upload_files`                      | Paths and the file input reference                                  |

Reads can take seconds for OCR or large documents; `read_id` pairs the start with
exactly one finished or failed event.

`open_file` and `open_downloaded_file` remain available for a visual preview.
`switch_tab` returns to the original page. DOM uploads through
`FileTools.upload_files` take workspace-relative paths. The whole selection is
checked before the bridge hands the files to Chrome. `open_file`,
`open_downloaded_file` and `upload_files` need a bridge (see below); without one
they are hidden. Put external files into the workspace from application code
before asking the agent to upload them.

Uploads accept an observed file input or its associated HTML label. Hidden or
covered file inputs do not need a clickable point; visible targets still get the
normal cursor and transfer animation. The live input is checked before assignment,
including whether it is disabled or accepts multiple files. No nearby input is
chosen implicitly when the target is not a file input or an associated label.

Direct Python callers open the workspace themselves; `FileTransfer` connects it
to a browser host through an explicitly chosen bridge. In an agent session,
`FileTransfers` binds Chrome's configured bridge to the current `FileSystem` and provides
`FileTransfer` as an optional service. `FileTools` consumes that service for
previews, uploads and download reception. A workspace change replaces the
transfer service without reopening Chrome; `Browser` does not expose the bridge.
Each download retains the transfer and workspace selected when it started.
After switching workspaces, downloads saved in another workspace have no accessible
`path` until that workspace is restored, so previews cannot open an unrelated file
with the same relative name. In-flight downloads finish in their original workspace.
For direct use:

```python
from browserrig import (
    ChromeBrowser,
    FileSystem,
    FileTransfer,
    LocalWorkspace,
    MountedWorkspace,
)
from browserrig.browser import Launch

async with (
    FileSystem(LocalWorkspace(".browserrig/research")) as files,
    ChromeBrowser(Launch()) as browser,
):
    transfer = FileTransfer(files, MountedWorkspace())
    await browser.receive_downloads(transfer)  # later downloads land in files
    document = await files.read_file("report.pdf", page_number=2)
    staged = await transfer.stage(["report.pdf"])
    await browser.tabs.open(staged.browser_paths[0])
```

`staged.browser_paths` are the files' paths on the browser host, which
`browser.tabs.open(...)` accepts as a `PurePath`. `tabs.open` only accepts
HTTP(S) URLs as strings. File operations are
asynchronous; blocking file work and document parsing run in worker threads.
Standalone synchronous programs can call these methods from an async entry point
using `asyncio.run`.

### Workspaces, bridges and remote browsers

Two interfaces separate _where the agent's files live_ from _how Chrome reaches
them_:

| Interface    | Responsibility                                                                                                        | Built in                              |
| ------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `Workspace`  | Stores the agent's files: `stat`, `list`, `read_bytes`, `write_bytes`. Paths are workspace-relative `PurePosixPath`s. | `LocalWorkspace(directory)`           |
| `FileBridge` | Moves files between the workspace and the machine that runs Chrome: `download_directory`, `receive`, `send`.          | `MountedWorkspace(browser_path=None)` |

Custom workspaces implement `write_bytes(path, data, *, overwrite=True)`.
With `overwrite=False`, creation must atomically fail with `FileExistsError` if
another file already exists, including concurrent writes. Use exclusive creation
on a local disk or the storage provider's conditional-create operation; a separate
existence check followed by an unconditional write cannot enforce this contract.

`MountedWorkspace` is for a browser that sees a `LocalWorkspace` directory on its
own file system: on the same machine, or on a pod that mounts the same volume.
Nothing is copied. Pass `browser_path` when Chrome sees the directory at another
absolute path, for example `MountedWorkspace("/workspace")` for a container mount.
A workspace the agent reaches only through an API needs its own `FileBridge`.

| Setup                                | Configuration                                                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Local Chrome (default)               | `Chrome.launch()` with the default `Files()`: a fresh `LocalWorkspace`, mounted for Chrome                            |
| Local Chrome, chosen directory       | `Chrome.launch()` with `Files(LocalWorkspace("research"))`                                                            |
| Chrome on a pod with a shared volume | `Chrome.connect(endpoint=endpoint, bridge=MountedWorkspace("/workspace"))` with `Files(LocalWorkspace("/mnt/agent"))` |
| Cloud browser with a file API        | `Chrome.connect(endpoint=endpoint, bridge=ProviderBridge(...))`                                                       |
| Remote browser, no file transfer     | `Chrome.connect(endpoint=endpoint)`: workspace tools only                                                             |
| No files at all                      | `without=(Files, FileTools)`                                                                                          |

`Chrome.launch` mounts the workspace for Chrome by default. `Chrome.connect` never
assumes that the browser shares the agent's disk: without a bridge, downloads stay
on the browser host and `open_file`, `open_downloaded_file` and `upload_files` are
hidden. Without `Files` there are no workspace tools.

A cloud browser provider usually exposes downloads and uploads through an API.
Implement `FileBridge` against it; the protocol is structural and needs no base
class:

```python
from collections.abc import Sequence
from pathlib import PurePath, PurePosixPath

from browserrig import (
    Agent,
    BrowserDownload,
    Chrome,
    Files,
    LocalWorkspace,
    Workspace,
)


class ProviderBridge:
    def __init__(self, session):
        self.session = session  # the provider's SDK session

    async def download_directory(self, workspace: Workspace) -> PurePath:
        # Where Chrome saves downloads on the provider's machine.
        return PurePosixPath("/tmp/downloads")

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        # Chrome names the file by download.id in the download directory.
        data = await self.session.files.read(f"/tmp/downloads/{download.id}")
        await workspace.write_bytes(destination, data)

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        remote = []
        for path in paths:
            target = PurePosixPath("/tmp/uploads") / path
            await self.session.files.write(
                str(target), await workspace.read_bytes(path)
            )
            remote.append(target)
        return remote


agent = Agent(
    model=model,
    browser=Chrome.connect(endpoint=session.cdp_url, bridge=ProviderBridge(session)),
    plugins=[Files(LocalWorkspace(".browserrig/research"))],
)
```

The workspace can be remote too, such as a bucket or a pod's file API: implement
`Workspace` and pass it to `Files(...)`. `write_bytes` replaces existing files;
`FileSystem` checks for them before writing without `overwrite`. A workspace
that needs setup, such as opening a client, can also be an async context
manager: the session enters it while the workspace is in use. Reading from a remote workspace parses a
local temporary copy, so `extracted_path` is `None` there; the text is still
returned and paginated. `LocalWorkspace` keeps the extraction under `.content/`.

A failing bridge never breaks the browser: the download ends as completed with an
error in `list_downloads`, and previews and uploads return a tool error.

### File access boundaries and optional sandboxes

Browserrig's built-in file tools confine reads, writes, listings, previews and
uploads to the workspace. Path traversal and symlinks resolving outside it are
rejected. Browserrig does not expose
a shell tool. Keep the workspace dedicated to agent files; anything placed in it
is available to the agent.

This is a tool-level path policy. Chrome, document parsers, custom Python plugins
and MCP servers still run with their process permissions. Concurrent host changes
to links or directories are outside this boundary. Application calls such as
`browser.tabs.open(Path(...))` and `Frame.upload_files(...)` remain trusted
host APIs. Use a separate OS/container boundary when the whole browser or parser
process must be isolated.

Harnessed also supports a filesystem-only runtime sandbox: compose
`DockerSandbox(...)` or `BubblewrapSandbox(...)` with `FilesystemTools()` and omit
`ShellTools()`. The shell service is then not exposed as a model tool. This is
opt-in and requires an application-managed Docker image or Linux rootfs; startup
failure never falls back to host execution. See the
[sandbox guide](https://github.com/mathisarends/harnessed/blob/v0.8.0/docs/guides/sandboxes.md).

These backends do not redirect Browserrig's local `FileTools`, uploads, Chrome
downloads or document readers. In a custom composition, omit Browserrig's
`Files` and `FileTools` before adding `FilesystemTools` to avoid duplicate
tool names and host file access through those tools. Transfer files explicitly
from application code; copied sandbox results must be exported before session
close. Browserrig does not implement Harnessed's `FileSystemBackend` protocol, so
the new `read_bytes`/`grep` backend contract needs no migration here.

The file reader uses a shared `FileExtension` enum and a registry of readers with
a common call signature and declared selection capabilities. New formats can be
registered without extending a central parser dispatch chain.

Chrome saves each download in the bridge's download directory
(`downloads/.pending/` for `MountedWorkspace`). When it completes, the bridge
stores it at `downloads/<download-id>/<filename>`, preserving the filename and
extension; duplicate filenames get separate folders. `DownloadState` includes `IN_PROGRESS`,
`COMPLETED`, and `CANCELED`; download events use the `browser.download.*` namespace.
`Download.total_bytes` is `None` when the server does not announce a size.
Canceled downloads emit `DownloadCanceledEvent` instead of `DownloadFailedEvent`.

Attaching to an existing `target_id` retains its browser-wide download policy, so
its downloads are not received into the workspace.
The OpenAI example accepts `--workspace .browserrig/research` to reuse a directory.

Subscribe to durable facts and live choreography from a session while a run is
active (for example, from a consumer task started before `session.run`):

```python
from browserrig.events import ActionStartedEvent, CursorMovedEvent, KeyPressedEvent

async for event in session.subscribe(transient=True):
    match event:
        case ActionStartedEvent(kind=kind):
            print(kind)
        case CursorMovedEvent(to_position=point, duration=duration):
            print("cursor", point, duration)
        case KeyPressedEvent(key=key):
            print("key", key)
```

Subscriptions observe future events and finish when the session closes.
`session.subscribe()` without `transient=True` continues to return durable facts only.

Import SDK events directly from `harnessed.events`, for example
`ToolCallRequestedEvent` and `ToolCallFinishedEvent`. The latter carries the final
reviewed result, including denied calls. Activity intervals use execution receipts
for tool timing and the SDK's `request_id` for model timing, including failures,
cancellations, and context-limit retries. Tool cancellation and timeout have
separate activity outcomes.

Compaction intervals use their own `compaction_id` and distinguish applied,
discarded, failed and cancelled attempts. They do not close an outstanding model
request. Live model attempts and compaction notifications are transient and are
not part of run results. Applied compactions remain durable events of their turn.
`session.stream()` forwards native model request/failure, attempt/retry and
compaction activity. A request, attempt or compaction finishing does not finish
the turn; use `TurnResultEvent.result` on normal stream exhaustion and release
live UI activity in `finally` on cancellation or stream failure.

Browser observations supply their snapshot ID through `observe(message, source="browser",
refs=(snapshot.id,))`. `ObservationRecordedEvent` carries `message`, `source` and
`refs` separately. Hints carry
their nudge IDs and are acknowledged only by `ObservationsIncludedEvent` for the
`browser.nudges` source. IDs appearing in ordinary text leave hints queued.
Receipts carry `refs`, `turn_id`, `step` and `message_id`; observations removed or
modified by request hooks or compaction receive no receipt. `NudgeIncludedEvent.request_id` matches the submitted request;
`SessionLog.included_observations(request)` exposes that provenance while the turn is
open; afterwards, read the `ObservationsIncludedEvent` from `result.events`.
Screenshot coordinates also follow these final receipts, rather than provisional
request content or SDK message-ID conventions.

## Finding and searching saved content

`glob(pattern="**/*", limit=200)` finds workspace files. `grep(query,
pattern="**/*.md", limit=100)` searches literal text case-insensitively and returns
`path:line` matches with bounded snippets and Unicode character offsets. Pass an
offset to `read_file` to inspect more context around a match. It searches complete UTF-8 files,
including text beyond `read_file` preview limits. Both operations use the existing
workspace, including custom/remote workspaces; no shell is required. The results
use Harnessed's `PathMatches` and `SearchResult` contracts.

Hidden files and directories, including `.content` and pending download caches,
are excluded unless `include_hidden=True`. Glob patterns are workspace-relative;
absolute paths and traversal outside the workspace are rejected. Directory walks
are bounded to 1,000 directories. Search checks at most 1,000 matching files and
`max_expanded_bytes` input bytes in total. Oversized/unreadable files, match limits
and incomplete walks are reported; a limited search is not proof of absence.

When an associated `.extraction.json` or webpage `source.json` reports pending OCR
or a partial extraction, search adds a coverage note even when there are no
matches. It searches saved text and never starts OCR implicitly. Run `read_file`
on the relevant source pages to extend the saved text before searching again.
