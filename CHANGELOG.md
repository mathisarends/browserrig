# Changelog

## Unreleased

### Breaking changes

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
  `FileSystem(workspace, options)`. `FileTransfer(files, browser.bridge)` replaces
  `files.resolve(path)` and `files.upload_paths(...)` with
  `await transfer.stage(paths)`, whose `browser_paths` `tabs.open(...)` accepts;
  direct `ChromeBrowser` users call `await browser.receive_downloads(transfer)` to
  save downloads into the workspace.
  A custom `Workspace` implements only `stat`, `list`, `read_bytes` and
  `write_bytes`; `MountedWorkspace` needs a `LocalWorkspace`.
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

- Upgrade Harnessed and all provider extras to 0.13.0. Rename `browser_kit()`
  to `browser_pack()`; it returns native `PluginPack`. Use `PluginPackPromptPolicy`
  and `pack_path` for resolution and provenance.
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
- **Storage reset required:** conversation state uses format 2, execution
  checkpoints and JSON stores format 3, audit envelopes version 5. Older formats
  are rejected without automatic migration. Back up application-owned data and
  start new snapshots, stores and audit logs.
- Human-handoff history persists through feature instruction state and is delivered
  by its own `PrepareRequest` hook. The removed `DynamicContext` service is no
  longer used. The `Done` output bridge dispatches by session log identity and
  restores native output methods after its last activation closes.

### Added

- Visualize file reads/writes, content extraction, listings, JavaScript, screenshots,
  history navigation, form changes, readiness, handoff and failures through shared
  typed `WorkPresentedEvent` receipts. The same transient stream supports the local
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
