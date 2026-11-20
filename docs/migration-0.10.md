# Migrate from 0.9.x to 0.10.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#0100-2026-11-20)

## Upgrade Harnessed

Browserrig 0.9 pins Harnessed 0.20.0. Browserrig 0.10 pins Harnessed and its
provider, MCP and OTel extras to 0.22.0.

1. Back up the session store before upgrading. In the existing 0.9 environment,
   open each conversation by ID, finish any open turn, and export the idle
   conversation using `session.snapshot().to_json()`.
2. Upgrade and open each conversation by ID using a fresh `JsonSessionStore`
   root and `state=SessionState.from_json(payload)`. Import `SessionState` from
   `harnessed.sessions`. The next turn writes a format 4 checkpoint. Standalone
   snapshots and the outer JSON store envelope still use format 3.
3. Keep the backup and old SDK for completed or paused format 3 checkpoints
   and archived version 6 audit records. Use a reader from the SDK that wrote the
   audit records. Switch live audit readers and writers together to version 7.

See the [Harnessed 0.21.0](https://github.com/mathisarends/harnessed/releases/tag/v0.21.0)
and [0.22.0 release notes](https://github.com/mathisarends/harnessed/releases/tag/v0.22.0).

## Move runtime settings out of the plugin list

| 0.9 | 0.10 |
| --- | --- |
| `plugins=[AgentLoop(...), Approvals(...), ...]` | `loop=AgentLoop(...), approvals=Approvals(...), plugins=[...]` |
| `prompt=SystemPrompt(...)` | `instructions=SystemPrompt(...)` |
| `AgentLoop(context_window=..., max_tool_output=...)` | `Context(max_tokens=..., max_tool_output_chars=...)` |
| `ContextCompaction(trigger=WindowRatio(...))` | `context=Context(compaction=Compaction(at=..., fallback_tokens=...))` |
| `TaskMemory(..., keep_last_steps=..., summarizer=...)` | Put summarizer and history limits in `Context(compaction=Compaction(...))` and add `TaskMemory(...)` for workspace guidance |
| `without=(ContextCompaction,)` | `without=(TaskMemory,)` to remove the default compaction and workspace guidance |
| `async with session.use(plugin)` | `async with session.mount(plugin)` |

Use a flat list of configured plugin instances and omit disabled capabilities.
Build conditional plugin lists by appending enabled plugins to the list.
Browserrig applies its defaults and slot overrides before passing that list to
Harnessed. Native Harnessed agents use the list as supplied.

Use `Decision` in place of `PolicyDecision`. Approval rules accept `ActionKind`
members or decorated tool references. To ask through an application, set
`approvals=Approvals(default=Decision.ASK, approver=...)` and return
`request.allow()` or `request.deny()` from the callback. For stream responses use
`session.approvals.allow(id, remember=...)` or `session.approvals.deny(id)`.
Browserrig follows Harnessed's default and permits tool calls, including side
effects, without confirmation. Set an explicit policy if your application needs
confirmation or an allowlist.

Import `Inject`, `PluginState` and `hook` from `harnessed.kernel`, tool metadata
and errors from `harnessed.tools`, and prompt types from `harnessed.prompts`.
If you use Harnessed's file and shell tools, supply the workspace provider
separately as in `[LocalWorkspace(root=path), Filesystem(), Shell()]` from
`harnessed.plugins`. Browserrig's `Files` and workspace tools keep their own
configuration.

## Update usage and tracing consumers

Read turn-level usage from `RunResult.usage` or `TurnEndedEvent.usage`.
`TerminalEvents()` emits it in the `turn.ended` JSON record. For tracing,
`OTLPTracing()` owns the exporter for each session and flushes on close. Keep
`OpenTelemetryTracer` for an application-owned provider. See
[telemetry](telemetry.md#use-in-an-application).

## Compose perception from plugins

`BrowserPerception` keeps the observation lifecycle: readiness, capture,
redaction, delivery and image history. What an observation contains comes from
plugins mounted beside it. `browserrig.Agent` includes `BrowserPerception()`,
`Screenshots()`, `DomPage()` and `SetOfMarks()`; pass a plugin to replace its
default or remove it with `without=`.

```python
# 0.9
BrowserPerception(
    text=TextObservations(mode="full"),
    capture=DomCapture(page_prose="sparse"),
    screenshots=Screenshots(
        trigger=ScreenshotTrigger.EACH_STEP,
        marks=SetOfMarks(),
        cursor=True,
    ),
)
```

```python
from browserrig import (
    BrowserPerception,
    CursorMarker,
    DomPage,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
)

plugins = [
    BrowserPerception(text="full"),
    DomPage(prose="sparse"),
    Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
    SetOfMarks(),
    CursorMarker(),
]
```

| 0.9 | 0.10 |
| --- | --- |
| `TextObservations(mode="delta")` / `mode="full"` | `BrowserPerception(text="delta")` / `"full"` |
| `TextObservations(content="metadata")` | Omit `DomPage`; without a page model, observations carry the metadata header |
| `DomCapture(page_prose=...)` | `DomPage(prose=...)` |
| `ScreenshotCapture()` | No page model: `BrowserPerception(text=None)` with `Screenshots` |
| `Screenshots(marks=SetOfMarks())` | `SetOfMarks()` plugin |
| `Screenshots(cursor=True)` | `CursorMarker()` plugin |
| `BrowserPerception(screenshots=Screenshots(...))` | `Screenshots(...)` plugin |

In the standard agent, change only what differs:

```python
from browserrig import Agent, DomPage, Screenshots, ScreenshotTrigger, SetOfMarks

agent = Agent(
    model=model,
    plugins=[Screenshots(trigger=ScreenshotTrigger.EACH_STEP)],
    without=(DomPage, SetOfMarks),
)
```

## Port custom capture strategies

Implement `PageModel` instead of `CaptureStrategy` and `Renderer`. `collect`
receives a `CaptureRequest` with the readiness report, screenshot flag, region,
zoom and cursor, and returns `PageCapture(page, references)`. `render(snapshot)`
formats the observation text. Register the model from a plugin during setup; the
plugin contributes its own instructions.

```python
from harnessed import Plugin
from harnessed.kernel import PluginScope, needs

from browserrig import BrowserPerception


class CanvasPage(Plugin):
    _perception = needs(BrowserPerception)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.use_model(CanvasModel()))
        scope.effect(self._perception.use_frames(CanvasFrames()))
```

`PageContent` lists `targets` and model-specific `parts` instead of DOM fields.
Subclass `Target` for model data and `PagePart` for page-level data; set `text`
to the raw page text so secret checks can withhold an image. `FrameSource`
supplies images when the viewport is not the right source, and
`ImageAnnotator` draws custom overlays. `supports_dom_refs` is gone: DOM tools
use `ResolveDomElement`, which `DomPage` provides.

## Read targets instead of elements

| 0.9 | 0.10 |
| --- | --- |
| `snapshot.elements` | `snapshot.targets` |
| `snapshot.element(ref)` | `snapshot.target(ref)` |
| `snapshot.headings`, `content`, `offscreen`, `modal`, `alerts`, `cookie_banners`, `canvases` | `DomView.of(snapshot).headings`, ... |
| `BrowserPerception.element(tab, ref)` | `BrowserPerception.target(tab, ref)` |
| `ElementHandle.element` | `TargetHandle.target` |
| `CaptureContent` | `PageCapture` |

DOM targets remain `ElementInfo` instances; `DomView.of(snapshot).elements`
returns them typed. `DomElementHandle.element` is unchanged.

## Update imports

DOM extraction, rendering, search and handles moved from `browserrig.observation`
to `browserrig.dom`, for example `DomReferences`, `ElementInfo`, `render`,
`search_content` and `extract_document`. Imports from the top-level `browserrig`
facade are unchanged for names that still exist.

## Snapshot serialization and fingerprints

`Snapshot.model_dump` and `model_dump_json` keep target and part fields, but
`Snapshot.model_validate_json` cannot restore DOM targets and parts. Keep your
own typed records if you persist snapshots for later validation. Page
fingerprints also cover the raw page text, so a stored 0.9 fingerprint does not
match a 0.10 fingerprint of the same page.
