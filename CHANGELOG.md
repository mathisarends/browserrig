# Changelog

## Unreleased

### Breaking changes

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
