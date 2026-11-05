# Changelog

## Unreleased

### Breaking changes

- Model screenshots omit the pointer marker by default. Use
  `DomCapture(cursor=True)` to opt into the existing post-capture marker.

- Rename the browser observation plugin from `Observe` to `BrowserPerception`,
  describing the page structure, element references and optional screenshots
  provided before each model step. Update recipes, dependencies, examples and
  documentation.
  Replace `Observe(...)`, `Inject[Observe]`, `dependency(Observe)` and type-based
  plugin exclusions with `BrowserPerception`. The old name is removed without an
  alias. Plugin descriptions and dependency diagnostics use `BrowserPerception`;
  observation events and the `browserrig.observation` plugin slot are unchanged.

- Require a `Chrome` plugin for `Agent(browser=...)`, `browser_kit(browser=...)`
  and `browser_plugins(browser=...)`. Replace `browser=Launch(...)` with
  `browser=Chrome.launch(...)` and `browser=Connect(...)` with
  `browser=Chrome.connect(...)`. Remove the top-level `Launch` and `Connect`
  exports; direct `ChromeBrowser(...)` callers can import these low-level
  configuration types from `browserrig.browser`.

- Pin Harnessed and all provider extras to the published 0.12.0 release.
- Replace `await session.context.set("constraints", "Include source URLs.")`
  with `await session.add_context("Include source URLs.")`. The native Harnessed
  session now has one API for adding background without starting a turn or making
  a model call. Each call appends a user-role text message, including duplicates;
  there are no keys, replacement or removal operations and no compatibility alias.
  Await it before starting dependent work. A configured store commits the write
  before it returns. Contributions survive turns and restoration as conversation
  history and follow ordinary compaction, which may summarize older text.
- Remove public `session.context` access. Inspect retained contributions through
  `session.messages` or `session.snapshot().history`. Plugin-owned named facts,
  including human-handoff receipts, remain in `session.snapshot().context`.
  Use `instructions=` for fixed rules and Harnessed's `ContextValue` plugin for
  changing named facts. Session storage formats are unchanged.

### Added

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

- Add `session.ctx[HumanHandoff].history` as an immutable tuple of typed,
  redacted `HandoffReceipt` records. Restore history before the first turn and
  keep JSON serialization and Harnessed's context storage inside the plugin.
- Expose `HandoffStatus` as a `StrEnum` for receipts, events and human responses.
  Use members such as `HandoffStatus.CANCELLED`; serialized status strings remain
  unchanged. Human responses still accept only `DONE` or `DECLINED`.
- Add `Chrome.launch(...)` and `Chrome.connect(...)` factories that return configured
  browser plugins for `Agent(browser=...)`, `browser_kit()`, `browser_plugins()` and
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
