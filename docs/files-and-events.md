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

## Downloads and events

Launched browsers automatically get a workspace under `.browserrig/files/<unique-id>/`
and save downloads in its `downloads/` directory. Files remain available after the
browser closes. Choose a reusable workspace explicitly:

```python
from pathlib import Path
from browserrig import Agent, FileSystemOptions, Launch

agent = Agent(
    model=model,
    browser=Launch(
        url="https://example.com",
        files=FileSystemOptions(directory=Path(".browserrig/research")),
    ),
)
```

`files` belongs to the browser options, so `browser_plugins()`, `Chrome` and
`ChromeBrowser` use it as well.
The constructor creates no files or directories; browser startup creates the directories.
File access is confined to the workspace and any explicitly configured download
directory, including checks for path traversal and symlinks leaving those roots.

The agent sees the workspace and its latest 20 downloads before every step.
File tools are available alongside the browser tools:

| Tool | Behavior |
| --- | --- |
| `list_files(path=".", offset=0, limit=100)` | List a directory; follow `next_offset` for more. |
| `read_file(path, page_number=None, sheet=None, cell_range=None, member=None, ocr=None, offset=0, max_chars=20000)` | Read native document content, worksheet cells, archive members or OCR text. Returns structure, limitations, a saved extraction path and continuation offsets. |
| `write_file(path, content, overwrite=False)` | Save UTF-8 text and create parent directories; overwriting requires an explicit flag. |
| `list_downloads()` | List download IDs, status, saved paths, and file errors. |
| `open_downloaded_file(download_id)` | Open a completed download in a new active tab. |
| `open_file(path)` | Open a workspace/download file in a new active tab. |

Pass paths returned by `list_files` or `list_downloads`, or paths relative to the
workspace. The normal installation (`uv sync --locked`) includes all file readers
and local CPU OCR; no separate parser extras, browser preview or screenshots are
needed to read supported content.

| Format | Content and selection |
| --- | --- |
| Text, Markdown, source code, JSON, XML, YAML, logs, subtitles | Text with encoding detection and character offsets. |
| CSV, TSV; XLSX/XLSM/XLTX/XLTM, XLS, ODS | Worksheet names and cell addresses; choose `sheet` and an A1 `cell_range`. XLSX includes formulas, stored results, number formats, merged and hidden ranges. |
| PDF | One page, defaulting to page 1; `page_count` exposes the remaining pages. Pages without native text use local OCR automatically. `ocr=True` explicitly requests full-page OCR; `ocr=False` disables it. |
| PNG, JPEG, TIFF, GIF, BMP, WEBP, ICO | Image metadata and local OCR text; `page_number` selects a frame in a multi-frame image. |
| DOCX, PPTX, ODT, ODP, RTF | Document text and tables; PPTX also exposes speaker notes and optional slide selection with `page_number`. |
| HTML/XHTML/SVG, MHTML, EPUB | Readable text; EPUB follows chapter order. Embedded images and document-specific resources have explicit limitations. |
| ZIP, TAR and compressed TAR; GZ, BZ2, XZ; EML, MBOX | Entry or attachment listings. Select `member="report.xlsx"`, `member="#1"`, or nested `member="bundle.zip!/report.xlsx"`; the same readers process the selected content. |
| SQLite | Table names and values; select a table with `sheet`. Binary BLOBs are identified by size. |
| Audio and video | Metadata only; no transcription or video understanding. |

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
`max_archive_depth` to 8. Exceeding a processing bound raises an explicit error.
Very large or sparse XLSX sheets expose a bounded initial view with a limitation
and support targeted `cell_range` reads elsewhere in the sheet. These processing
bounds are separate from response pagination.

`FileTools` includes workspace operations, downloads and `upload_files`.
Omit it with `without=(FileTools,)` to remove the entire file capability.

File tools report facts as durable `browser.files.*` events, registered by
`FileTools` (`FILE_EVENTS` and `UPLOAD_EVENTS`). Presentation,
such as a file drawer, is left to the viewer:

| Event | Emitted by | Payload |
| --- | --- | --- |
| `FilesListedEvent` | `list_files` | Directory, entry count and pagination offsets |
| `FileReadStartedEvent` | `read_file` | `read_id`, requested path and selectors |
| `FileReadFinishedEvent` | `read_file` | `read_id`, path, format, status, character count, pages and offsets |
| `FileReadFailedEvent` | `read_file` | `read_id`, requested path and reason, including cancellation |
| `FileWrittenEvent` | `write_file` | Path, size and whether the file was created |
| `FileOpenedEvent` | `open_file`, `open_downloaded_file` | Path, `FileSource` and download ID; `target_id` is the new tab |
| `FilesUploadedEvent` | `upload_files` | Paths and the file input reference |

Reads can take seconds for OCR or large documents; `read_id` pairs the start with
exactly one finished or failed event.

`open_file` and `open_downloaded_file` remain available for a visual preview.
`switch_tab` returns to the original page. DOM uploads through
`FileTools.upload_files` accept workspace-relative paths or absolute paths
returned by file tools. Every selected file must exist within the workspace or
configured download directory; the whole selection is checked before browser
input. Uploads are disabled without a shared local filesystem, including remote
browsers without explicit `FileSystemOptions`. Stage external files in the workspace
from application code before asking the agent to upload them.

Direct Python callers can use `await browser.files.read_file(path, page_number=2)` and
`await browser.tabs.open(await browser.files.resolve(path))`; `tabs.open` opens a `Path`
as a local file and only accepts HTTP(S) URLs as strings. Filesystem operations are
asynchronous: await initialization, path resolution, existence checks, reads, writes,
listings, upload validation and download completion. Blocking filesystem work and
document parsing run internally in worker threads. Standalone synchronous programs
can call these methods from an async entry point using `asyncio.run`.

### File access boundaries and optional sandboxes

Browserrig's built-in file tools confine reads, writes, listings, previews and
uploads to the configured workspace and download directory. Path traversal and
symlinks resolving outside those roots are rejected. Browserrig does not expose
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
`FileTools` before adding `FilesystemTools` to avoid duplicate
tool names and host file access through those tools. Transfer files explicitly
from application code; copied sandbox results must be exported before session
close. Browserrig does not implement Harnessed's `FileSystemBackend` protocol, so
the new `read_bytes`/`grep` backend contract needs no migration here.

The file reader uses a shared `FileExtension` enum and a registry of readers with
a common call signature and declared selection capabilities. New formats can be
registered without extending a central parser dispatch chain.

`Launch(download_directory="ABSOLUTE_PATH_ON_BROWSER_HOST")` overrides the
download location. Downloads first use `.pending/` and then move into a folder
named by their stable download ID, preserving their filename and extension.
Duplicate filenames get separate folders. `DownloadState` includes `IN_PROGRESS`,
`COMPLETED`, and `CANCELED`; download events use the `browser.download.*` namespace.
`Download.total_bytes` is `None` when the server does not announce a size.
Canceled downloads emit `DownloadCanceledEvent` instead of `DownloadFailedEvent`.

Connected browsers keep their existing host semantics: `Connect` enables
workspace tools only when `Connect(files=FileSystemOptions(...))` explicitly identifies
a directory shared with the browser host at the same absolute path. Without it,
download tracking still works but local file reads and previews are unavailable.
Attaching to an existing `target_id` retains its browser-wide download policy.
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
the turn; use `TurnFinishedEvent.result` on normal stream exhaustion and release
live UI activity in `finally` on cancellation or stream failure.

Browser observations carry their snapshot ID in `Observation.refs`. Hints carry
their nudge IDs and are acknowledged only by `ObservationsIncludedEvent` for the
`browser.nudges` source. IDs appearing in ordinary text leave hints queued.
Receipts carry `refs`, `turn_id`, `step` and `message_id`; observations removed or
modified by request hooks or compaction receive no receipt. `NudgeIncludedEvent.request_id` matches the submitted request;
`SessionLog.included_observations(request)` exposes that provenance while the turn is
open; afterwards, read the `ObservationsIncludedEvent` from `result.events`.
Screenshot coordinates also follow these final receipts, rather than provisional
request content or SDK message-ID conventions.
