# Compose a browser agent

Harnessed `Agent` is the composition root. Browserrig plugins own session state,
tools and hooks; ordinary Python strategies implement capture, rendering,
readiness and action-chain decisions. Browserrig targets Harnessed 0.7.0.

## A browser agent with screenshots

```python
from harnessed import Agent
from browserrig import (
    Actions, Activity, Chrome, DomCapture, DomRenderer, DomTools,
    ImageContext, KeyboardTools, LaunchBrowser, NavigationTools, Observe,
    PointerTools, Readiness, Screenshots, ScreenshotTrigger, TabTools,
    TrimInBatches,
)

agent = Agent(
    model=model,
    plugins=[
        Chrome(LaunchBrowser(url=url)),
        Readiness(),
        Observe(
            capture=DomCapture(),
            renderer=DomRenderer(),
            screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
        ),
        ImageContext(TrimInBatches(max_images=6, min_images=3)),
        Actions(),
        DomTools(),
        PointerTools(),
        KeyboardTools(),
        NavigationTools(),
        TabTools(),
        Activity(),
    ],
)
```

Add `DialogTools`, `JavaScriptTools`, `FileTools`, `UploadTools` or `Nudges`
from their packages as needed. `UploadTools` requires DOM refs and a
browser file workspace. The same readiness checks apply to web pages and
local document previews.

`DomTools` owns ref-based click, drag, typing and form tools; `PointerTools`
uses screenshot or viewport coordinates, and `KeyboardTools` sends input to the
current focus. DOM tools validate the capture's `provides_dom_refs` capability at
setup. Empty pages can still have that capability. `Actions()` uses
`DomActionChains()` for captures with refs; `ObserveAfterInput()` requires a fresh
observation after each input when selected explicitly.

## Human handoff

For optional human login and takeover, add `HumanHandoff(ask=...)` to the plugin
list or pass it as `handoff=` to `BrowserAgent` / `browser_plugins()`.
See [human handoff](human-handoff.md) for host callbacks, typed receipts and
pause/resume context. It is absent from the default recipe.

## Screenshot settings

| Setting | Meaning |
| --- | --- |
| `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` | One new screenshot at the observation boundary before each model step. |
| `Screenshots(trigger=ScreenshotTrigger.ON_REQUEST)` | Capture at the next boundary only after the `screenshot` tool was called. This is the default for explicit composition. |
| `ImageContext(TrimInBatches(max_images=6, min_images=3))` | Keep up to six captures; when a seventh arrives, drop the oldest until three remain. Defaults: `max_images=1`, `min_images=max_images // 2` (at least one). Both must be positive integers with `min_images <= max_images`. `ImageContext()` keeps one image. |
| `ImageContext(UntilCompaction())` | Never trim. Images leave history when compaction summarizes the steps they were captured in. Use it with a `Compaction` plugin, otherwise image history grows without limit. |
| `ImageContext(..., skip_unchanged=False)` | Also add captures identical to the latest image. By default, a capture with the same pixels, crop, tab and document is not added again, and the last line of the request says the screen is unchanged. |

Calling `screenshot` with `EACH_STEP` does not create a second image. There is no
separate observe tool: every step ends with an observation, and `wait` covers
pages that are still updating. Internal
readiness and action-comparison probes never enter image history. Text-only steps
retain included images across turns until compaction or an explicit observation
policy removes their snapshots.
Unmounting the plugin or opening a new session resets its live coordinate state.
The captured observations and images remain in the durable session log for audit
and manual replay. A new browser session obtains fresh state before acting.

DOM text, a fixed screenshot caption and image form one native multimodal
`Observation(content=..., refs=(snapshot.id,))`. Harnessed stores inline images as
session-owned `ImageReference` assets before recording. JSONL stores the references;
binary image data lives under `<session-id>.assets/` and is resolved only for
selected provider requests. Keep that directory with the history when backing it up.

Text observations remain unchanged in history until native compaction removes
their steps. `browser_plugins()` does not install `LatestObservationOnly()`.
Ordinary steps append to a stable prefix; image batch trimming deliberately
removes older image parts while preserving their DOM text. A modified observation
loses its inclusion receipt. Custom retention implements
`ImageRetention.overflow(count)`, the number of oldest images to drop after a capture.

With `ImageContext(UntilCompaction())`, text and images leave together in the
request applying the summary. There is no extra request of image retention and
no special exemption for the latest screenshot. For long tasks, configure native
compaction, for example:

```python
from harnessed.plugins import Compaction
from browserrig import BrowserAgent, ImageContext, UntilCompaction

agent = BrowserAgent(
    model=model,
    image_context=ImageContext(UntilCompaction()),
    plugins=[Compaction(
        trigger=lambda state: state.input_tokens >= 32000,
        keep_steps=4,
    )],
)
```

The token threshold works without knowing the model's context window; tune it
and the retained steps for the task. Without compaction, text history and
`UntilCompaction` image history grow with the conversation. The OpenAI example
uses this policy. To explicitly keep only the latest snapshot per source, pass
`plugins=[LatestObservationOnly()]`, importing it from `harnessed.plugins`.
This also removes an older screenshot when a new text-only browser snapshot
replaces it and changes the request prefix at every replacement.

Coordinate tools select the latest image confirmed by
`ObservationsIncludedEvent`, after all request hooks and compaction. They match
native `refs`, without parsing message IDs. Images retain ID, UTC capture time,
browser/tab/document, viewport dimensions and crop/scale. Text-only steps keep
the last included image's geometry while its observation remains in the request.
If no screenshot is included, tools use viewport CSS pixels. An included image
from another document cannot supply coordinates for the current page.

The last request line names the latest *captured* screenshot, which request hooks
or compaction may remove; final inclusion receipts determine coordinate geometry.
After a layout change, request a fresh screenshot. With Anthropic models, place
the cache breakpoint before the newest observation.

## Extension contracts

Import these protocols from `browserrig` or their service packages. Strategies are
reusable configuration objects; mutable state belongs in each probe or plugin's
`PluginState`, never in a shared recipe object.

| Contract | Implementation |
| --- | --- |
| `CaptureStrategy` | Declare `provides_dom_refs`; implement `collect(tab, report, *, screenshots, region=None, zoom=1, cursor=None) -> CaptureContent`. Honor `screenshots=False`. The runner handles dialogs, document coherence, fingerprints and snapshots. |
| `Renderer` | `instructions(screenshots)`, `refs()` and `render(snapshot)`. Pure presentation, no browser input or waits. |
| `ReadinessPolicy` | `create(context) -> ReadinessStrategy`, returning a fresh probe. Context supplies tab, stage, phase and options. |
| `ReadinessStrategy` | `budget`, `delay`, `reason`; `async check() -> bool`; `timeout_status()`. The shared runner owns deadlines, dialogs, cancellation and events. |
| `ActionChainPolicy` (`browserrig.tools`) | `async check(observe, tab) -> str`: empty allows continuing; otherwise explain why a fresh observation is required. Failed comparison ends the chain without turning successful input into failed input. |

## Initial readiness and ongoing readiness

`Readiness(initial=..., ongoing=...)` selects initial readiness until a document
passes with `READY`. Failed, blocked or degraded initialization is not marked as
successful. State is local to a browser service mount and keyed by tab/document.
Navigating to another document initializes that document; switching back to a tab
with the same document does not restart initialization. Use `readiness.invalidate(tab)`
for application resets without a document-ID change. This cancels waits for that
document and requires a fresh initial readiness check.

The independent event fields are:

- `stage`: `initial` or `ongoing`.
- `phase`: `observation` before capture, `action` before input/comparison,
  `after_action` after input, or `navigation` after a navigation tool. The legacy
  explicit `initial` phase remains accepted.

Concurrent waits share work only for the same document, stage and phase. A waiter
cancelling does not cancel other waiters; plugin teardown/abort does cancel owned
tasks. If the document changes while probing, the plugin selects readiness again
for the new document. A policy factory must create a new mutable probe each time.

## Native stream events

Consume `session.stream(...)` inside `agent.session()`. There is no Browserrig
projection layer or output-profile switch. Own events use the existing SDK:

```python
from dataclasses import dataclass
from typing import Literal
from harnessed import Inject, Plugin, SessionLog, hook
from harnessed.events import DurableEvent
from harnessed.hooks import Next, PreStep, StepDecision

@dataclass(frozen=True)
class AppReady(DurableEvent):
    type: Literal["myapp.ready"] = "myapp.ready"

class AppEvents(Plugin):
    events = (AppReady,)

    @hook(PreStep)
    async def report(self, event: PreStep, next_: Next[StepDecision], log: Inject[SessionLog]):
        await log.emit(AppReady())
        return await next_()
```

Registered custom `DurableEvent` and `TransientEvent` subclasses emitted during a
turn both reach its native stream. Only durable events enter the session log.
Browserrig observations and readiness use durable events; pointer/keyboard motion
uses transient events. `ObservationCapturedEvent` carries identity and metadata,
not screenshot Base64. Setup events emitted before the stream begins are not
replayed automatically. Native SDK bookkeeping has its own stream projection;
custom-event support does not imply every persisted SDK event appears in a turn stream.

## Existing applications

`BrowserAgent` and `browser_plugins()` remain convenience recipes. Configure
observations with `observe=Observe(capture=DomCapture(...), screenshots=Screenshots(...))`.
Composition also accepts `readiness=Readiness(...)`,
`image_context=ImageContext(...)`, `actions=Actions(...)` and `local_files=False`
when local file tools should be omitted.

The default recipe mounts `DomTools`; custom captures without refs omit DOM and
upload tools. Transient availability (for example a missing workspace) still uses
tool gates, including execution-time rechecks. Existing upload path validation is retained.
Keep file readers as ordinary functions/strategies, not one plugin per file format.

For manual compositions, add `ImageContext()` explicitly: `Observe` no longer
injects images itself. Configure `Readiness` and `Observe` independently. Move
`type_text` from custom `KeyboardTools` compositions into `DomTools`. `MouseTools` remains a compatibility group for DOM
and coordinate mouse tools; do not install it alongside overlapping tool groups.
Harnessed filesystem tools can replace local file tools by selecting
`local_files=False`; browser download paths are not automatically sandbox paths.
