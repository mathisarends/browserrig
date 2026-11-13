# Files and events

[Back to README](../README.md) · [Composition](browser-composition.md)

## Workspace tools

The agent has one workspace. Paths returned by tools are relative to it, such as
`notes/summary.md` or `downloads/<id>/report.pdf`. The default `Files()` creates a
fresh local workspace per session under `.browserrig/files/`; files remain after
closure. Choose an explicit directory for reuse:

```python
from browserrig import Agent, FileOptions, Files, LocalWorkspace

agent = Agent(
    model=model,
    plugins=[Files(
        LocalWorkspace(".browserrig/research"),
        options=FileOptions(max_file_bytes=20_000_000),
    )],
)
```

| Plugin | Capability |
| --- | --- |
| `Files` | Provides `FileSystem` over a `Workspace` |
| `WorkspaceTools` | List, read, write, edit, glob and grep; works without a browser |
| `BrowserFileTools` | Download listing and file previews |
| `DomUploadTools` | Upload workspace files to observed DOM inputs |
| `FileTools` | Combined workspace, preview and DOM upload tools |
| `FileTransfers` | Binds the workspace and a `FileBridge` into `FileTransfer` |
| `DownloadReceiving` | Receives later browser downloads independently of tool availability |
| `PageExtractionTools` | Saves loaded webpage content to workspace Markdown |

`WorkspaceTools`, `BrowserFileTools` and `FileTools` share one slot; choose one.
The task recipe includes the combined tools. Removing tools does not stop download
receiving. To omit files from that recipe, remove
`without=(Files, FileTools, PageExtractionTools)`. Manual browser/file compositions
also need `FileTransfers()` and `DownloadReceiving()` for receiving downloads.

A workspace-only agent uses Harnessed `Agent` with
`plugins=[Files(LocalWorkspace(directory)), WorkspaceTools()]`. Configure approvals
for writes as usual.

## Reading and searching

| Operation | Use |
| --- | --- |
| `list_files(path=".", offset=0, limit=100)` | Directory entries; follow `next_offset` |
| `read_file(path, ...)` | Text, document selections or visual content |
| `write_file(path, content, overwrite=False, append=False)` | Create, explicitly overwrite, or append UTF-8 text |
| `edit_file(path, old_text, new_text, replace_all=False)` | Exact text replacement; one match unless explicitly replacing all |
| `glob(pattern="**/*", limit=200)` | Find paths |
| `grep(query, pattern="**/*.md", limit=20)` | Case-insensitive literal matches with bounded snippets and offsets |

Finish a text selection with `next_offset` before following `next_page_number` or
`next_sheet`; retain the same selectors. Search is bounded and reports incomplete
coverage. Hidden directories/caches are excluded unless `include_hidden=True`.

The base package reads plain text and supports image previews. Install
`browserrig[files]` for document, spreadsheet, PDF and media readers, or
`browserrig[ocr]` for those readers plus local CPU OCR.

| Selection | Behavior |
| --- | --- |
| `view="auto"` | Default model tool view: images as visual content, other files as text |
| `view="image", page_number=12` | PDF page or image frame; PNG preview bounded to 2048 pixels, without OCR |
| `view="text"` | Text extraction; images can use OCR |
| `page_number=...`, `ocr=True` | Select a PDF page and explicitly request OCR |
| `sheet=...`, `cell_range="A1:D20"` | Target worksheet cells; formulas are not recalculated |
| `member=...` | Select an archive member |
| `offset=...`, `max_chars=...` | Read a bounded text excerpt |

Direct `FileSystem.read_file` calls default to text; visual results expose
`FileContent.image`. Model tools return image content parts. Status and
`limitations` identify partial, unsupported or metadata-only reads. OCR, graphics
and stored formula results need interpretation; source files are preserved and
macros/scripts are not executed.

## Saved webpage extractions

`extract_content(full_page=False, name=None)` saves a new `pages/<id>/content.md`
and `source.json` containing URL, title, time and limitations. A `name` makes the
path predictable (`pages/<name>/content.md`) and replaces an earlier save with it. The tool returns only
the receipt. Use `grep(query, pattern=<saved-path>)` and `read_file` for excerpts;
the file stays readable after navigation.

Extraction reads loaded DOM content, including available shadow/frame documents,
without navigating or loading lazy content. It omits hidden text, scripts and
form values; truncation and unavailable frames are reported. Configured secrets
are redacted before persistence. The direct Python helper
`browserrig.observation.content.extract_content(tab, ...)` returns typed Markdown
without requiring a workspace.

## Downloads and previews

Completed downloads retain the source and, by default, create adjacent `.md` and
`.extraction.json` sidecars in background indexing. `list_downloads()` reports
transfer and extraction status separately. `open_downloaded_file(download_id)`
and `open_file(path)` open previews in a new tab; uploads use workspace-relative
paths and an observed file input or its associated label.

PDF indexing scans native text within configured bounds (default 2,000 pages),
then OCRs up to three textless pages when OCR is available. Set
`auto_ocr_pages=0` to defer OCR or `auto_extract=False` to disable sidecars. Explicit
page/sheet reads extend the index; `grep` searches saved text without starting
OCR. Partial coverage is reported even when a search finds no matches.

`FileOptions` bounds parser inputs/writes (default 50 MB), expanded data (200 MB)
and archive depth (8). These limits are separate from response pagination.

## Workspaces, bridges and remote browsers

File storage and browser access have separate contracts:

| Contract | Responsibility |
| --- | --- |
| `Workspace` | `stat`, `list`, `read_bytes`, `write_bytes` using workspace-relative paths |
| `FileBridge` | `download_directory`, `receive`, `send` between the workspace and browser host |

`Chrome.launch()` uses a mounted local workspace by default. `Chrome.connect()`
assumes no shared disk: without a bridge, files remain on the browser host and
previews/uploads are unavailable. A shared-volume deployment can configure:

```python
from browserrig import Chrome, Files, LocalWorkspace, MountedWorkspace

browser = Chrome.connect(
    endpoint=endpoint,
    bridge=MountedWorkspace("/workspace"),
)
files = Files(LocalWorkspace("/mnt/agent"))
```

Both paths must name the same mounted volume. For a cloud browser, implement
`FileBridge` against the provider's file API. Remote storage can independently
implement `Workspace` and be passed to `Files(...)`. Custom
`write_bytes(..., overwrite=False)` must provide atomic exclusive creation.

Changing workspace rebinds file transfers without reopening Chrome. In-flight
downloads finish in their original workspace; their paths are unavailable in an
unrelated workspace. Attaching to an existing `target_id` preserves its download
policy, so its downloads are not received into the workspace.

## File access boundaries and optional sandboxes

Built-in file tools reject absolute paths, traversal and links escaping the
workspace. The workspace is a tool-level path boundary; Chrome, parsers and
custom plugins retain their process permissions. Use a separate OS/container
boundary when the entire process needs isolation.

Harnessed filesystem/sandbox tools can replace local file tools. Remove `Files`,
`FileTools` and `PageExtractionTools` from the task recipe first, and transfer
browser files explicitly. A sandbox does not automatically redirect Chrome,
Browserrig readers or downloads.

## Event streams

Use the native turn stream for model and browser events:

```python
async with agent.session() as session:
    async with session.stream("Inspect the page.") as run:
        async for event in run:
            await render_event(event)
        result = await run.result()
```

For an independent viewer, start a consumer before the run and iterate
`session.subscribe(transient=True)`. Subscriptions observe future events and end
when the session closes; omit `transient=True` for durable facts only.

| Event family | Meaning |
| --- | --- |
| Durable browser events | Navigation, actions, observations, readiness, downloads and file operations |
| Transient input/work events | Cursor, keys, scroll, progress and viewer presentation |
| Harnessed events | Model/tool calls, retry activity, control changes and compaction |

Import browser events from `browserrig.events` and runtime events from
`harnessed.events`. Browser receipts carry browser/tab/document identity; action
receipts and input events share `action_id`. File reads use `read_id`, model calls
use `request_id`, and compaction attempts use `compaction_id`.

`ObservationsIncludedEvent` confirms the final observation references after
request processing and compaction. Screenshot geometry and nudge acknowledgement
follow these receipts. Transient presentation events stay out of model context
and persisted results. `TurnResultEvent` marks normal turn completion; request or
compaction completion does not. Release viewer activity in `finally` on failures.
