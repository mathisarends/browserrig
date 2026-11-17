# Changelog

## Unreleased

### Breaking changes

- Replace `DomPerception`, `TextContext` and `ImageContext` with one
  `BrowserPerception(text=..., screenshots=...)`. Use `DomText(mode="delta")`
  or `DomText(mode="full")` for text, and `None` to omit text. Use
  `Screenshots(...)` for images, and `None` to omit images. Add
  `marks=SetOfMarks()` for labeled targets in either image mode. Images without
  text or marks use screenshot capture and browser-event readiness without DOM
  extraction. Images with marks still collect DOM targets. The default
  `browser_pack()` keeps DOM text and marked screenshots on request.
- Move `marks`, `cursor`, `skip_unchanged` and image `retention` to
  `Screenshots`. For a fresh image on every model step, use
  `Screenshots(trigger=ScreenshotTrigger.EACH_STEP, skip_unchanged=False)`.
  `ScreenshotTools()` remains separate. Image-only sessions configured for
  on-request capture receive an initial image for each document they enter.
  With known `Secrets` values, screenshot-only capture withholds images because
  it has no DOM data for redaction.
- `DomCapture` and the low-level `capture(..., screenshots=True)` return
  unannotated pixels. Perception applies image marks and cursor overlays when
  projecting a model observation. Custom text renderers implement
  `instructions()` without a screenshot argument.
- `DomElements` is now the callable service `ResolveDomElement`. Replace
  `await scope[DomElements].resolve(tab, ref)` with
  `await scope[ResolveDomElement](tab, ref)`. `BrowserPerception` provides the new
  service key; import it from `browserrig` or `browserrig.observation`.
- Custom `Motor` implementations must provide
  `wheel_steps(delta_x=..., delta_y=...)`, returning `WheelStep` values from
  `browserrig.input` with native CSS-pixel deltas and `delay_before_seconds`.
  The deltas must total the requested distance. Inherit from `Instant` or
  `HumanMotor` to reuse a built-in wheel plan (#61).

### Changes

- Add `WheelTools()` for native scrolling at the pointer in screenshot-based
  sessions. WebArena selects a variant with `--observation text`,
  `screenshot`, `screenshot-marks`, `text-screenshot`, or
  `text-screenshot-marks`. Timing and tool availability are configurable via
  `--screenshot-trigger` and `--screenshot-tool` / `--no-screenshot-tool`.
- Enforce the reviewed Smelt source and test conventions as errors, including
  stateful dataclasses and repeated lifecycle narrowing assertions. Keep only
  the three documented import/navigation review heuristics as visible hints.
- Wheel scrolling follows the motor installed by `InputPacing`. `HumanMotor`
  accelerates and decelerates gently; `scroll_speed=0.5` doubles the gesture's
  duration and `scroll_speed=2` halves it. `Instant` sends one wheel event
  without pauses. Slow browser replies extend smooth gestures instead of
  causing larger catch-up jumps (#61).

## 0.6.0 (2026-11-16)

Upgrade from 0.5.x using the [migration guide](docs/migration-0.6.md).

### Breaking changes

- Numeric Browserrig durations name their units. Replace `timeout=` with
  `timeout_seconds=` in `Chrome.launch`/`connect`, `Launch`/`Connect`,
  `HumanHandoff`, `Tab.evaluate`, `Tabs.opened_since` and `execute_javascript`.
  `ReadinessOptions` uses `timeout_seconds` and `poll_interval_seconds`;
  `HumanMotor` uses `typing_interval_seconds`. Input paths, drag APIs and tools,
  readiness reports and browser/choreography event payloads use
  `duration_seconds`; `RecordingResult` exposes `original_duration_seconds`
  and `duration_seconds`. Update custom event viewers and persisted payloads;
  the built-in overlay and terminal consumers are migrated. Values remain in
  seconds. Existing `_ms` fields and upstream CDP/HTTP/animation APIs are unchanged.
- Replace `DomCapture(max_text_chars=..., sparse_text_chars=...)` with
  `DomCapture(text=PageText.INLINE | PageText.SPARSE | PageText.OFF,
  max_text_chars=...)`. `PageText.OFF` omits prose between controls; `SPARSE`
  uses `max_text_chars` as its budget. `max_text_chars` must be at least 1, and
  `sparse_text_chars` is removed. `DomRenderer(text=...)` replaces its `max_text_chars` and
  `sparse_text_chars` fields. Defaults are unchanged.

### Changes

- Add opt-in `ActionLabels()`, registering the `ActionLabel` envelope and emitting
  `ToolCallPresentedEvent` with an immutable, automatically redacted
  `event.envelope.action_label`. Hosts need no helper or session scope. Requested
  and finished events cover browser, file and foreign-plugin calls, including
  failures and cancellation. Work and action events also carry redacted labels;
  the built-in overlay keeps its fixed captions (#51).
- `ActionStartedEvent`, `ActionFinishedEvent` and `ActionFailedEvent` carry the
  originating tool `call_id` and a short display `label` (at most 80 characters;
  the tool name when no model label is supplied). Failure and cancellation keep both, and
  action receipts join their tool receipt by `call_id`. `Actions.run(label=...)`
  names explicitly managed operations.
- Add `Chrome.connect(downloads=...)` with a `DownloadSource` protocol so a host
  that owns an attached browser's download policy can relay its download events;
  browserrig then tracks and presents those downloads without taking over files.
- Add `DomCapture(headings=True, landmarks=True)`. Turning both off together
  with `text=PageText.OFF` leaves only controls with their labels; dialogs and
  cookie banners stay grouped. `DomRenderer(landmarks=...)` adjusts its
  instructions accordingly.
- Add `--page-text`, `--no-headings` and `--no-landmarks` to the WebArena
  runner and record them in results, so observation arms can be compared.
- Upgrade Harnessed and every provider/MCP/OTel extra to 0.18.0, which adds
  registry-wide call envelopes (`CallEnvelope`). No Browserrig code changes are
  required.
- Upgrade development checks to Smelt 0.10.0 and adopt reviewed guardrails for
  duration names and frozen dataclass fields; see the development policy guide.

## 0.5.0 (2026-11-15)

### Breaking changes

- Split choreography into an event producer and an in-page consumer.
  `InputVisualization` is now `Choreography` and only emits events; the new
  `ChoreographyOverlay` plugin draws them inside the active tab and takes
  `name`, `keyboard_layout` and `theme` directly. `IframeRenderer` and the
  `renderer` parameter are removed: replace `InputVisualization(renderer=None)`
  with `without=(ChoreographyOverlay,)` and
  `InputVisualization(renderer=IframeRenderer(...))` with
  `ChoreographyOverlay(...)`. Both are browser defaults; drop both with
  `without=(InputPacing, Choreography, ChoreographyOverlay)` to work unseen.
  Bare harnessed agents mount `ChoreographyOverlay()` next to `Choreography()`
  to keep the in-page rendering; the overlay requires `Choreography`.
- Separate browser facts from presentation. `Choreography` projects downloads,
  uploads and activities into `DownloadPresentedEvent`,
  `UploadPresentedEvent` and `ActivityPresentedEvent`, which share the new
  `PresentedEvent` base with `WorkPresentedEvent`. Viewers, including the
  overlay, draw only input and presented events and no longer interpret
  `Download*Event`, `FilesUploadedEvent` or `Activity*Event` facts.
- Optional flags and tuning parameters of tool methods are keyword-only when
  called from Python: `PointerTools.click`/`click_at` (`count`, `button`,
  `new_tab`), `PageSearchTools.search_page` (`full_page`, `start`,
  `max_results`) and `WorkspaceTools.grep` (`limit`, `include_hidden`),
  `write_file` (`overwrite`, `append`) and `edit_file` (`replace_all`).
  `FileTransfer.receive` takes `browser_path=` by keyword. Agent tool calls are
  unchanged.
- Name the fields of fixed-length tuples. Coordinates are `Position(x, y)`,
  aim spots `Aim(x, y)` and find-mark rectangles `Box(x, y, width, height)`;
  all remain tuples, so unpacking and serialized receipts are unchanged.
  `Tab.viewport_size()` and custom `InputTarget.viewport_size()` implementations
  use `ViewportSize`; replace tuple unpacking with `.width`/`.height`.
  `Tab.dialog` is an `OpenDialog(kind, message)`, `Motor.aim_fractions` returns `Aim`,
  `CursorPath` has `control_point_1`/`control_point_2` instead of
  `control_points`, and `CursorPath.curved(bend=...)` takes a `Bend`.
  `ControlPoint` is removed in favour of `Position`.

### Changes

- `Choreography` republishes the resting cursor when the active tab settles on a
  new document, so every viewer, not only the in-page overlay, can redraw it.
- Upgrade Harnessed and every provider/MCP/OTel extra to 0.17.0. No Browserrig
  code changes are required.
- Add the source viewport to coordinate receipts. Cursor, pointer, wheel,
  highlight, find, file-transfer and tab-press events now derive from
  `PositionedEvent` and carry `viewport` (`ViewportSize`), measured when the
  receipt is emitted; screenshot `WorkPresentedEvent`s carry it with their
  `CaptureRegion`. External renderers can project input across tab switches and
  live resizes without querying the browser later.
- Fix missing choreography for DOM scroll tools: `Choreography` now emits
  separate transient `PageScrolledEvent` and `ElementScrolledEvent` receipts
  with public `tab_id` and measured deltas (`ref` identifies an element) when
  `scroll_page` or `scroll_element` actually moves. Wheel events retain their
  native-input semantics.
- Stage the browser's own controls for viewers. Before typing an address the
  pointer focuses the address bar (`AddressBarFocusedEvent`); `go_back`,
  `go_forward` and `reload` press their buttons first (`BackPressedEvent`,
  `ForwardPressedEvent`, `ReloadPressedEvent`, staged through `ControlIntent`).
  Each is a `PositionedEvent` with the pointer's origin and travel duration; a
  `CursorEnteredEvent` returns the pointer into the page afterwards, at once
  when the step fails or is cancelled. Viewers that draw their own toolbar place the controls
  themselves; nothing extra is clicked in the browser.

### Fixed

- Retry a favicon download interrupted by an in-page title or icon update; a
  cancelled load no longer leaves the icon URL cached without its image.
- Keep HTML files checked out with LF line endings so the JavaScript format
  check also passes on Windows with `core.autocrlf=true`.
- `TabStrip` follows title and favicon changes made in the page without a
  navigation, including idle single-page-app updates and removed icons. The
  workaround of calling `tab.report_change(settled=not tab.loading)` after each
  tool is no longer needed (#47).

## 0.4.0 (2026-11-14)

### Breaking changes

- Remove `extract_content`, `PageExtractionTools`, `PageContentExtracted`,
  `save_content` and the reading sweep (`ReadingSweepEvent`). `search_page`
  reads page content without saving it; collect findings across pages in
  workspace notes. `PageContent` no longer has `extracted_path` or
  `render_receipt()`.
- Remove `find_in_page`, `FindTools` and `FindIntent`; `search_page` replaces
  them. Viewers see a search as Ctrl+F with live match marks and scrollbar
  ticks, staged through `SearchIntent`, and the page never scrolls.
  `FindResultsEvent` replaces `active` with the bar's `label` and adds `ticks`.

### Changes

- Add `search_page`, a read-only page search that returns matching table rows
  with their column headers, list items and paragraphs, including links, without
  scrolling or saving the page.
- Encourage batched tool calls in DOM chain and workspace guidance.
- Evals record chain-skipped tool calls as `tool_skipped`, not as tool errors.

### Fixed

- Keep the visible search match in long record excerpts even when preceding
  whitespace is collapsed or link destinations contain the query. Match
  decomposed accents consistently with precomposed text.
- Stabilize navigation guard integration setup and readiness timeout assertions
  on slower runners and Windows clocks.

## 0.3.0 (2026-11-11)

### Breaking changes

- Move input ownership from Chrome into explicit Runtime and InputRuntime plugins.
  Chrome provides input-target transports; devices, pacing and presentation use
  Input directly. Share task-local action correlation independently of devices.
  Decouple tab operations through ChangeTab hooks and lifecycle events, including
  cursor restoration and cleanup. Add Targeting for reference location and bounded
  hover preparation; remove Actions' browser/perception/readiness forwarding.
  Manual compositions and low-level input callers must migrate as documented in
  docs/browser-composition.md.

- Remove `zoom` from the screenshot tool; cropped screenshots retain their
  coordinate mapping. Lower-level Python screenshot APIs keep their zoom option.

- Separate observation, text/image context and tool capabilities for explicit
  Harnessed compositions. Add DomPerception, TextContext, DomTypingTools,
  DomScrollTools, DomUploadTools, ScreenshotTools and PageExtractionTools.
  BrowserPerception now requires capture/renderer and exposes no tools; DOM tools
  depend on the typed DomElements resolver. Actions defaults to observing after
  input; legacy task defaults explicitly keep DOM chains and their existing tools.
  Extraction presentation receives a typed redacted event instead of perception
  state. See the composition guide for migration from direct plugin constructions.

- Save agent `extract_content` results as workspace Markdown and return only
  `Saved`, `Source`, `Title` and actual extraction limitations. Remove its inline
  body and `max_chars`/`offset` arguments. `PageExtractionTools` requires a
  workspace; to omit files from the default recipe, use
  `without=(Files, FileTools, PageExtractionTools)`. Direct Python Markdown
  extraction and full typed presentation data remain available.
- Upgrade Harnessed and every provider/MCP/OTel extra to 0.16.0. `TaskMemory`
  accepts `llm`, replacement `prompt` factories, `keep_last_steps`, whole-input
  targets and `max_summary_tokens`; custom summarizers now accept
  `CompactionRequest` and return `Summary`. State/checkpoint format 3 and audit
  envelope 6 reject older data: start new stores and retain the original
  application environment for older conversations and checkpoints.
- Replace the agent's `scroll` tool with `scroll_page` and `scroll_element(ref=...)`.
  Both scroll their named target directly, independently of the cursor, and report
  actual movement or a blocked/boundary result. Container scrolling never propagates
  to ancestors. Native wheel input remains available through the session's
  `Input` service as `session.scope[Input].mouse.scroll(...)`; direct Python
  callers construct `Input(browser.input_targets.focused)`.

### Added and changed

- Expose explicit radio values/IDs/groups, control title guidance, native option
  values and multi-select states. Add `select_options` to replace and verify an
  exact native multiple-selection set with whole-request validation.
- Add bounded workspace `grep` and `glob` tools for targeted reads of saved
  extractions. Workspace, browser-file and DOM-upload tools can be composed
  independently through `WorkspaceTools`, `BrowserFileTools` and `DomUploadTools`.
- Automatically create searchable Markdown sidecars for completed downloads,
  with extraction status, source metadata and bounded OCR coverage. Add visual
  `read_file` views for PDF pages and image frames without running OCR.
- Apply a shared GPT-6.1 Terra profile to regular agents and benchmarks: a
  256,000-token application context limit, 8,192-token output reserve, two retained
  steps, a 40% compaction target and an 8,192-token summary ceiling. Benchmark
  result files record these settings. Other models retain their existing defaults.

- Interleave visible text with controls in a typed `PageContent.content` tree.
  Paragraphs retain inline `[label][ref]` links, form guidance stays beside its
  fields, and code keeps its line breaks. Preserve frame insertion order,
  viewport previews and source-based label deduplication; mark text truncation
  locally while retaining later controls. Existing flat capture backends remain
  supported through `content=None`.

- Add `read_todos()` for explicit plan recall; stale-plan reminders now name the
  tools instead of repeating the list. Reads also refresh the reminder interval.
- Use `TaskMemory` in the default browser pack: working notes remain in
  `notes/task_state.md`, with one checkpoint reminder before compaction and a
  targeted read after it. Compaction can defer once within the existing budget.
  Correlated `TaskMemoryEvent` receipts and `browserrig.memory` spans record saved
  file revisions and incomplete recovery without logging note bodies as metadata.
  Native `ContextCompaction(...)` remains available to opt out.

- Add `edit_file(path, old_text, new_text, replace_all=False)` to the workspace
  tools. It replaces exact text in a UTF-8 file and fails when `old_text` is
  missing or ambiguous, so the agent can update notes without rewriting them.
  `write_file` gains `append=True`, which adds to the end and creates a missing
  file. Both emit `FileWrittenEvent`; `FileSystem` has matching methods.

- Add opt-in `Todos()` with Pydantic `Todo` and `TodoList` models. `update_todos`
  saves a bounded plan with stable IDs and at most one step in progress, and
  returns the list as its result. Open lists are reminded only when no update is
  left in context (e.g. after compaction) or the last one is `remind_after` steps
  old. Lists persist with the session's feature state.

- `Done` defers structured output through the session-scoped `PrepareOutput`
  hook instead of patching Harnessed's global output handler. `browser_tool`
  attaches its activation binding through the public `registration()` helper.

- Shorten agent-facing tool descriptions, move parameter details to their schema
  and share file workflows through plugin instructions. Coordinate rules live in
  "Screenshot coordinates", form batching moved into "Browser action chains"
  (`FormTools` no longer adds a "Form filling" block), and details already
  shown by observation labels or tool descriptions were removed.

### Fixed

- Reveal DOM input targets by scrolling their exact containers, avoiding unrelated
  editor wheel interception. Report bounded, measured auto-scroll positions in
  success and failure receipts. Keep custom backend wheel planning unchanged.
- Fix false hit-test clipping for fixed-body pages with a zero-height HTML root.
  Report bounded hit-test layout diagnostics without page text or field values.
  Remind agents to verify intended effects in the next observation; tool
  acknowledgements describe attempted interactions, not application success.
- Preserve selected chips when typing into an empty native text field. Skip the
  empty-field Backspace and stop remaining text if focus leaves the addressed
  field or its embedding frame.
- Keep download receiving and cleanup independent of the exposed file tools and
  tolerate browser closure before download cleanup.

## 0.2.0 (2026-11-09)

### Breaking changes

- `browser_tool` requires an async callback. Synchronous callbacks now fail at
  declaration time instead of silently skipping the browser action pipeline.
  Mark a synchronous decorator wrapper that returns a coroutine with
  `inspect.markcoroutinefunction`.

- Download receiving belongs to the new `DownloadReceiving()` plugin, included
  in the default browser pack. Removing `FileTools` only removes model tools;
  remove `DownloadReceiving` to stop receiving later downloads. Manual
  compositions add it alongside `FileTransfers()` to save browser downloads.

- Headed `Chrome.launch(...)` no longer pins `viewport` as device metrics; it sets
  the initial window size and pages follow the window when a person resizes it.
  Headless launches and `Chrome.connect(viewport=...)` still pin the viewport.
  After a resize, coordinate tools reject outdated observations and screenshots,
  and `Nudges` tells the agent the old and new viewport size.

- File readers and OCR are optional. The base installation reads plain text;
  install `browserrig[files]` for document, spreadsheet, PDF and media readers, or
  `browserrig[ocr]` for those readers plus local CPU OCR (RapidOCR, ONNX Runtime,
  OpenCV, PDFium). Without them, `read_file` names the missing extra and returns
  raw text for text-based formats.

- Pin Harnessed and all provider/MCP/OTel extras to 0.14.0. Migrate plugin lifecycle
  methods to `PluginScope`, and compose `FileTransfers()` explicitly in the browser
  pack. Manual Chrome/Files/FileTools compositions must add `FileTransfers()`.
  Human handoff uses a per-activation `timeout_seconds` resolver. Replace local
  tracing helpers with `harnessed.tracing`; library spans use full `browserrig.*`
  names and standard source attributes. Truncated captured content remains JSON.

- Group browser devices under `browser.input.mouse` and `browser.input.keyboard`;
  the direct `browser.mouse` and `browser.keyboard` aliases are removed.
  Move `action_lock` off `Browser`: inject the session's `BrowserCoordination`
  service and use `async with coordination.exclusive():` for operations that
  share control with actions, observations and human handoff.
  `Browser.bridge` is removed. `Chrome` publishes its configured `FileBridge`;
  `FileTransfers()` binds it to the optional workspace and provides `FileTransfer`
  for `FileTools` and other consumers. Direct callers construct
  `FileTransfer(files, bridge)` explicitly.

- Split the agent's files into a `Workspace` (where files live) and a
  `FileBridge` (how Chrome reaches them), so downloads and uploads also work with
  browsers on another pod or a cloud browser provider. Downloads land in the
  workspace's `downloads/` folder, and file tools, events and `Download.path` use
  workspace-relative paths such as `downloads/<id>/report.pdf`.
  The workspace is no longer a browser option: the new `Files` plugin, part of
  the default recipe, opens it as the session's `FileSystem` service. Replace
  `Chrome.launch(files=FileSystemOptions(directory=...))` with
  `plugins=[Files(LocalWorkspace(...))]`; processing limits move to
  `Files(options=FileOptions(...))`. `download_directory=` is removed: browsers
  take a `bridge=`, either `MountedWorkspace(browser_path)` for a shared volume
  or a `FileBridge` for a provider's file API. `Chrome.launch()` defaults to
  `MountedWorkspace()`; `Chrome.connect()` has no bridge, so previews and uploads
  are hidden and downloads stay on the browser host. Omit all file tools with
  `without=(Files, FileTools)`.
  `browser.files` is removed and `FileSystem(options)` becomes
  `FileSystem(workspace, options)`. `FileTransfer(files, bridge)` replaces
  `files.resolve(path)` and `files.upload_paths(...)` with
  `await transfer.stage(paths)`, whose `browser_paths` `tabs.open(...)` accepts;
  direct `ChromeBrowser` users call `await browser.receive_downloads(transfer)` to
  save downloads into the workspace.
  A custom `Workspace` implements only `stat`, `list`, `read_bytes` and
  `write_bytes`; `write_bytes(path, data, *, overwrite=True)` must atomically
  reject existing files with `FileExistsError` when `overwrite=False`, including
  concurrent creates. `MountedWorkspace` needs a `LocalWorkspace`.
  `FileSystemState` reports `workspace: bool` and a relative
  `download_directory`, and `FileContent.extracted_path` is relative to the
  workspace, or `None` for a remote workspace.

- `Presenter.leave(...)` and `Presenter.enter(...)` receive the current action as a
  keyword argument, `action_id`, the same way `show(...)` receives events that
  already carry it. `Stage()` takes no arguments; replace
  `Stage(lambda: browser.input.action_id)` with `Stage()`. Custom presenters add
  `*, action_id: str` to both methods.

- Model screenshots omit the pointer marker by default. Use
  `DomCapture(cursor=True)` to opt into the existing post-capture marker.

- Default DOM observations include up to 3,000 characters of visible page text
  and a 1,000-pixel context buffer for nearby controls. Set
  `DomCapture(max_text_chars=0, sparse_text_chars=0, viewport_expansion=0)` to retain
  strict controls-only viewport observations. Comparison probes still omit text.

- Rename the browser observation plugin from `Observe` to `BrowserPerception`,
  describing the page structure, element references and optional screenshots
  provided before each model step. Update recipes, dependencies, examples and
  documentation.
  Replace `Observe(...)`, `Inject[Observe]`, `needs(Observe)` and type-based
  plugin exclusions with `BrowserPerception`. The old name is removed without an
  alias. Plugin descriptions and dependency diagnostics use `BrowserPerception`;
  observation events and the `browserrig.observation` plugin slot are unchanged.

- Require a `Chrome` plugin for `Agent(browser=...)`, `browser_pack(browser=...)`
  and `browser_plugins(browser=...)`. Replace `browser=Launch(...)` with
  `browser=Chrome.launch(...)` and `browser=Connect(...)` with
  `browser=Chrome.connect(...)`. Remove the top-level `Launch` and `Connect`
  exports; direct `ChromeBrowser(...)` callers can import these low-level
  configuration types from `browserrig.browser`.

- Rename `browser_kit()` to `browser_pack()`; it returns native `PluginPack`.
  Use `PluginPackPromptPolicy` and `pack_path` for resolution and provenance.
- Replace `session.add_context(text)` and former named context writes with
  `await session.append_message(UserMessage(text))` (`harnessed.models`). Input is
  additive and durable, follows normal compaction, and starts no turn. Use
  `PrepareRequest` hooks for changing, request-only facts.
- Resolve application services through `session.scope`; import `Scope` from
  `harnessed.kernel`. Plugin lifetime fields use `needs(T)` / `observes(T)`;
  setup/teardown injection moves into fields. Tool contexts use `Inject[ToolContext]`.
  Plugins and runtime hooks receive restricted `SessionContext`.
- Open event streams with `async with session.stream(...) as run`; iterate `run`
  and await `run.result()`. Completion-only handles from `submit()` are not streams.
  Use `session.use(...)` for temporary capabilities and `await session.mount(...)`
  for manually managed lifetimes. Terminal events are `TurnResultEvent`; control
  events are `SessionControlChangedEvent`. Observations pass ordinary `UserMessage`
  values with separate `source=` and `refs=` arguments.
- Native agents collect plugin instructions by default. Remove `PluginOrder`;
  preserve `SystemPrompt.from_plugins(format=...)` to choose a format.
  `SystemPrompt(...)` explicitly omits plugin blocks, with omissions listed by
  `print(agent.prompt)`.
- **Storage reset required when upgrading from Harnessed 0.12 or older:**
  conversation state uses format 2, execution
  checkpoints and JSON stores format 3, audit envelopes version 5. Older formats
  are rejected without automatic migration. Back up application-owned data and
  start new snapshots, stores and audit logs. Harnessed 0.13 data already uses
  these formats and needs no migration for 0.14.
- Human-handoff history persists through feature instruction state and is delivered
  by its own `PrepareRequest` hook. The removed `DynamicContext` service is no
  longer used. The `Done` output bridge dispatches by session log identity and
  restores native output methods after its last activation closes.

### Added

- Compose `WorkspaceTools()` for browser-independent list/read/write tools and
  `BrowserFileTools()` for download listing, file previews and uploads.
  `FileTools()` remains the combined convenience group in the default pack. The
  three groups share one slot, so either group replaces the default in place.

- The observation facade exports `Canvas`, `Heading`, `Modal`, `Offscreen` and
  `Option`, completing the nested data types used by public capture contracts.

- Export `ActionKind` and `FileTransfers` from `browserrig` for custom tools and
  explicit plugin compositions.

- `VideoRecording` also writes the uncut session film as `original.mp4`, exposed as
  `RecordingResult.original_path`, in the same FFmpeg pass as the edited `video.mp4`.
- Add lock-wait, file/transfer/worker, navigation/JavaScript and presentation spans.
  Examples accept `--trace-hooks` for Harnessed hook timing independently of content
  capture. Turn summaries and model definitions/settings/schemas are captured when
  requested. See the telemetry guide for diagnosing harness and browser bottlenecks.
- `click` and `click_at` take `new_tab=True` to Ctrl+click (Cmd on macOS) a link
  into a new tab; the keyboard visualization shows the held key. Page input that
  opens a tab, including `target=_blank` links and `window.open`, now switches
  to the new tab and waits for its page instead of staying on the old one.
  `Keyboard.hold(...)` holds modifiers around other input, and `Mouse.click`
  takes their `modifiers`.

- Visualize file reads/writes, content extraction, listings, JavaScript, screenshots,
  history navigation, form changes, handoff and failures through shared
  typed `WorkPresentedEvent` receipts. The local overlay shows them on the page
  (a reading sweep over the extracted area, screenshot viewfinder, file flights,
  history cards, a handoff edge) with one caption instead of a card stack.
  Extraction results carry the visible area they read as `region`. The same transient stream supports the local
  inert overlay and external Canvas viewers, including previews, source geometry,
  result metadata and explicit terminal states. Restore fresh receipts after
  navigation and keep concurrent downloads independent.

- Readiness waits for the requests a click, input or navigation started
  (`NetworkQuiet`, now the default policy), so observations no longer miss
  results that arrive after the DOM was briefly quiet. Sockets, streams, polling
  that was not caused by the action and other background traffic never count, and
  the network adds at most 2 s to any wait.
- `Done` now prepares for the step limit. On the last step that still leaves room
  for a final answer, the agent is told to call `done`, and other tools are denied.
  After `done`, tools stay declared but are denied instead of being removed from the
  request, which keeps the prompt cache valid for the final answer.
- Render input choreography directly in the active tab with `IframeRenderer`,
  enabled by default in `InputVisualization`. Named cursors, precise target
  corners, full DE/EN keyboards, scroll wheels, file cards and find/address
  previews are captured in native session videos. Configure dark/light/auto
  themes; reduced motion, narrow viewports and protected input are supported.
  `InputVisualization(renderer=None)` retains event-only presentation.
- Add independent, browser-owned `tab.overlays.mount(...)` surfaces. Their inert
  iframes stay out of page extraction, search and readiness. Ordinary screenshots
  hide them temporarily; paired browser capture receipts let video recording
  stop and resume around those windows without blank overlay frames.
- Add `examples.visualization`, a local demo producing viewer and observation
  screenshot galleries and a recording without a model or API key.
- Add `ScrollStartedEvent` before native wheel dispatch so viewers can show
  scrolling while it happens; `ScrolledEvent` retains the final dispatched totals.

- Add opt-in `VideoRecording` using cdpify's native Page screen recording commands.
  Follow active tabs, finalize before controlled tab closure, and use Activity
  intervals to cut model, compaction and pause waits at session exit. Retain raw
  captures and a cut manifest, export MP4 through FFmpeg, and expose `--video`
  in the OpenAI example.

- Add `session.scope[HumanHandoff].history` as an immutable tuple of typed,
  redacted `HandoffReceipt` records. Restore history before the first turn and
  keep JSON serialization and Harnessed's context storage inside the plugin.
- Expose `HandoffStatus` as a `StrEnum` for receipts, events and human responses.
  Use members such as `HandoffStatus.CANCELLED`; serialized status strings remain
  unchanged. Human responses still accept only `DONE` or `DECLINED`.
- Add `Chrome.launch(...)` and `Chrome.connect(...)` factories that return configured
  browser plugins for `Agent(browser=...)`, `browser_pack()`, `browser_plugins()` and
  explicit Harnessed plugin composition. Configuration is validated immediately;
  browser resources open per session.

### Fixed

- Input motor and presenter overrides can be removed in any order, including
  repeated removal and multiple registrations of the same configuration instance.
  Removing another plugin no longer reactivates an already removed override.

- Keep a screenshot's resize revision so returning to the original window size
  cannot reactivate outdated screenshot coordinates.
- Ignore placeholder viewport dimensions from dialogs and unavailable captures
  when reporting window resizes.
- Enforce `overwrite=False` at the workspace write, preventing concurrent file
  creation from silently overwriting another writer's content.
- Coordinate parallel remote file reads and use unique temporary cache files.
- Keep in-flight downloads bound to their original workspace and bridge when
  file services change. Hide paths belonging to another workspace until it is
  restored, preventing previews from opening an unrelated file at the same path.
- Align Harnessed compatibility documentation with the pinned 0.14.0 release and
  validate Browserrig imports in Python documentation examples.
- Reject unavailable history navigation before marking an action as dispatched.
- Split native recordings at model, compaction and pause boundaries to keep stale
  wait frames out of the edited film while retaining them in `original.mp4`.

## 0.1.0 (2026-11-03)

Initial public release of Browserrig, a Python library for event-driven Chrome
automation and Harnessed browser agents.

- Launch Chrome locally or connect through CDP, with independent tab sessions.
- Observe pages through structured DOM content, element references and screenshots.
- Interact through browser tools, action chains, keyboard input and pointer gestures.
- Download, upload and read workspace files, including document parsing and local OCR.
- Compose browser capabilities with Harnessed plugins, typed events, session controls,
  telemetry and human handoff.
- Pin Harnessed and all provider extras to 0.11.0. Accept native `store=` for
  persistent conversations, paused recovery and atomic application-owned projections.
- Resolve flat browser plugins through public `Kit.resolve()` with recursive kit
  prompt omission; expose native provenance inspection through `browser_kit()`.
- Accept native trace redaction policies and application content filters in the
  shared example telemetry helper, with lazy optional imports.
- Upgrade development checks to Smelt 0.5.0 with an offline editor schema,
  grouped debt baseline and additional source/test rules. Preserve explicitly
  supplied falsy options and strategies instead of replacing them with defaults.

Python 3.12–3.14 is covered by CI on Windows and Linux; real Chrome integration
tests run on Linux. macOS requires explicit Chrome selection and has no CI coverage.
Perspective-transformed frames and browser process crash recovery remain limitations.
The 0.1 API may change between minor versions.
