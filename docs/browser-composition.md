# Compose a browser agent

Harnessed `Agent` is the composition root. Browserrig plugins own session state,
tools and hooks; ordinary Python strategies implement capture, rendering,
readiness and action-chain decisions. Harnessed 0.6.0 needs no changes.

## A browser agent with screenshots

```python
from harnessed import Agent
from harnessed.plugins import LatestObservationOnly
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
        LatestObservationOnly(),
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

## Screenshot settings

| Setting | Meaning |
| --- | --- |
| `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` | One new screenshot at the observation boundary before each model step. |
| `Screenshots(trigger=ScreenshotTrigger.ON_REQUEST)` | Capture at the next boundary only after the `screenshot` tool was called. This is the default for explicit composition. |
| `ImageContext(TrimInBatches(max_images=6, min_images=3))` | Keep up to six captures; when a seventh arrives, drop the oldest until three remain. Defaults: `max_images=1`, `min_images=max_images // 2` (at least one). Both must be positive integers with `min_images <= max_images`. `ImageContext()` keeps one image. |
| `ImageContext(UntilCompaction())` | Never trim. Images leave history when compaction summarizes the steps they were captured in. Use it with a `Compaction` plugin, otherwise image history grows without limit. |
| `ImageContext(..., skip_unchanged=False)` | Also add captures identical to the latest image. By default, a capture with the same pixels, crop, tab and document is not added again, and the last line of the request says the screen is unchanged. |

Calling `screenshot` with `EACH_STEP` does not create a second image. `observe`
refreshes text and refs without returning an image in the tool result. Internal
readiness and action-comparison probes never enter image history. Without a new
capture, the image buffer stays unchanged, including across turns in a live session.
Unmounting the plugin or opening a new session resets that buffer; it is not a
persisted image replay store.

The current `Snapshot`, last image included in a model request, and bounded image
history are distinct. Images retain ID, UTC capture time, browser/tab/document,
viewport dimensions and crop/scale. A text-only observation keeps the last shown
image's coordinate space. Images from other documents remain comparison material;
coordinate input rejects them until a new screenshot is shown. The last line of each
request names the latest screenshot. After a layout change, request a fresh screenshot.

Each image sits directly after the browser observation it was captured with and keeps
a fixed caption, so earlier requests stay a prefix of later ones and provider prompt
caching keeps working while images accumulate. Trimming in batches changes that
prefix once per `max_images - min_images + 1` captures instead of on every step.
After a compaction, images whose observation was summarized are dropped from the next
request on; the latest image always stays, because coordinate tools use it. Images
whose observation was only dropped by `LatestObservationOnly` stay in place until then.
Custom retention implements `ImageRetention.overflow(count)`, the number of oldest
images to drop after one was added.
With Anthropic models, place the cache breakpoint before the newest observation.

## Extension contracts

Import these protocols from `browserrig` or their service packages. Strategies are
reusable configuration objects; mutable state belongs in each probe or plugin's
`PluginState`, never in a shared recipe object.

| Contract | Implementation |
| --- | --- |
| `CaptureStrategy` | Declare `kind` (a presentation category) and `provides_dom_refs`; implement `collect(tab, report, *, screenshots, region=None, zoom=1) -> CaptureContent`. Honor `screenshots=False`. The runner handles dialogs, document coherence, fingerprints and snapshots. |
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

`BrowserAgent` and `browser_plugins()` remain convenience recipes. `mode=DomMode(...)`
configures DOM observations and their screenshot defaults. New composition uses
`observe=Observe(...)`, `readiness=Readiness(...)`,
`image_context=ImageContext(...)`, `actions=Actions(...)` and `local_files=False`
when local file tools should be omitted. Choose `mode` or `observe`, not both.

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
