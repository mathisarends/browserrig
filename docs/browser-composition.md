# Compose a browser agent

Harnessed `Agent` is the composition root. Browserrig plugins own session state,
tools and hooks; ordinary Python strategies implement capture, rendering,
readiness and action-chain decisions. Browserrig targets Harnessed 0.11.0.

## A browser agent with screenshots

```python
from harnessed import Agent, PluginOrder, SystemPrompt
from browserrig import (
    Actions, Activity, Chrome, DomCapture, DomRenderer, FormTools,
    ImageContext, KeyboardTools, NavigationTools, Observe,
    PointerTools, Readiness, Screenshots, ScreenshotTrigger, TabTools,
    TrimInBatches,
)

agent = Agent(
    model=model,
    instructions="Complete the browser task.",
    prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
    plugins=[
        Chrome.launch(url=url),
        Readiness(),
        Observe(
            capture=DomCapture(),
            renderer=DomRenderer(),
            screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
        ),
        ImageContext(TrimInBatches(max_images=6, min_images=3)),
        PointerTools(),
        Actions(),
        KeyboardTools(),
        FormTools(),
        NavigationTools(),
        TabTools(),
        Activity(),
    ],
)
```

Add `DialogTools`, `JavaScriptTools`, `FileTools` or `Nudges`
from their packages as needed. `FileTools` includes uploads from the shared browser workspace. The same readiness checks apply to web pages and
local document previews.

Tool groups follow the input device, not the capture: `PointerTools` clicks and drags by
screenshot or viewport coordinates and by ref, `KeyboardTools` sends keys to the current
focus and types into a ref, and `FormTools` sets native form controls. `Actions()` uses `DomActionChains()`;
`ObserveAfterInput()` requires a fresh observation after each input when selected
explicitly.

## Browser configuration

`Chrome.launch(...)` and `Chrome.connect(...)` return configured `Chrome` plugins.
The calls validate settings; resources open only when the agent session opens.
Each session launches a fresh owned process or opens a fresh connection. Session
exit stops a launched process and leaves an externally managed process running.

The same plugin works with the Browserrig recipe:

```python
from browserrig import Agent, Chrome

agent = Agent(
    model=model,
    browser=Chrome.connect(endpoint="http://localhost:9222"),
)
```

Connecting normally creates a fresh isolated browser context. Pass `target_id=...`
to select an existing tab; its URL and browser-wide download policy are preserved.
`endpoint` and `headers` accept strings or Pydantic `SecretStr` values and are
stored as secrets.

`Launch` and `Connect` remain available for existing code and direct
`ChromeBrowser(...)` use. `Agent`, `browser_kit()` and `browser_plugins()` accept
both these options and a configured `Chrome` plugin.

## Human handoff

For optional human login and takeover, add `HumanHandoff(ask=...)` to the plugin
list of `Agent` or `browser_plugins()`.
See [human handoff](human-handoff.md) for host callbacks, typed receipts and
pause/resume context. It is absent from the default recipe.

## Screenshot settings

| Setting | Meaning |
| --- | --- |
| `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` | One new screenshot at the observation boundary before each model step. |
| `Screenshots(trigger=ScreenshotTrigger.ON_REQUEST)` | Capture at the next boundary only after the `screenshot` tool was called. This is the default for explicit composition. |
| `ImageContext(TrimInBatches(max_images=6, min_images=3))` | Keep up to six captures; when a seventh arrives, drop the oldest until three remain. Defaults: `max_images=1`, `min_images=max_images // 2` (at least one). Both must be positive integers with `min_images <= max_images`. `ImageContext()` keeps one image. |
| `ImageContext(UntilCompaction())` | Never trim. Images leave history when compaction summarizes the steps they were captured in. Use it with a `ContextCompaction` plugin, otherwise image history grows without limit. |
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
session-owned `ImageReference` assets before recording. Conversation snapshots and
persistent execution checkpoints include the retained image bytes; the JSON codec
encodes them as Base64. Images resolve only for selected provider requests.

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
from browserrig import ContextCompaction
from browserrig import Agent, ImageContext, UntilCompaction

agent = Agent(
    model=model,
    plugins=[ImageContext(UntilCompaction()), ContextCompaction(
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
| `SessionSetup` | `async apply(cdp, *, frame) -> None`. Install ordered entries with `Chrome.launch(session_setup=(setup, ...))` or `Chrome.connect(session_setup=(setup, ...))`. Each new page or out-of-process frame session enables page, lifecycle and runtime first, then the browser applies viewport metrics to pages and runs each entry. `Viewport` only holds configuration data. |
| `CaptureStrategy` | Implement `collect(tab, report, *, screenshots, region=None, zoom=1, cursor=None) -> CaptureContent`. Return `PageContent` and optional per-observation `references`. Honor `screenshots=False`. Set `CaptureContent.fingerprint` to supply a comparison key; `None` keeps the DOM semantic fingerprint. The runner handles dialogs, document coherence and snapshots. |
| `References` | `async resolve(tab, snapshot, ref) -> ElementHandle`. Resolve an opaque ref from the published observation without input. Supply a fresh resolver with each capture; `None` uses `DomReferences`. |
| `ElementHandle` | `element: ElementInfo`; `async locate(*, aim=None) -> ElementPoint`. Validate the live target and return a hit-tested point and bounds in viewport CSS pixels. `aim` is a preferred pair of fractions within the visible target. Input runs through `Mouse`, `Keyboard` and their `Motor`. |
| `ScrollableElement` | Optional `async scroll_step() -> ScrollStep | None`. Plan one wheel input with a viewport `point`, `delta_x`, `delta_y` and a `key` identifying the current plan. The shared runner sends ordinary mouse input and bounds retries. |
| `Renderer` | `instructions(screenshots)`, `refs()` and `render(snapshot)`. Pure presentation, no browser input or waits. |
| `ReadinessPolicy` | `create(context) -> ReadinessStrategy`, returning a fresh probe. Context supplies tab, stage, phase and options. |
| `ReadinessStrategy` | `budget`, `delay`, `reason`; `async check() -> bool`; `timeout_status()`. The shared runner owns deadlines, dialogs, cancellation and events. |
| `SelectReadiness` | Native Harnessed `Bail[ReadinessPolicy]`: the first non-`None` policy overrides the configured initial/ongoing policy for this document. |
| `CheckReadiness` | Native Harnessed `Waterfall[ReadinessCheck]`: call `await next_()` and compose application conditions around the selected policy. The shared deadline includes the middleware. |
| `Motor` (`browserrig.input`) | `keystrokes(text, *, sensitive) -> Sequence[KeyStroke]`, `pointer_route(start, destination) -> Sequence[CursorPath]`, `aim_fractions(target_width, target_height) -> tuple[float, float]`, `press()` and `landing(viewport_width, viewport_height)`. How input is performed; install it with `InputPacing(motor)`. A plan types characters and may correct slips with `Backspace`; sensitive text must be typed exactly. A route's strokes join end to start. No events, no viewer concerns. |
| `Presenter` (`browserrig.input`) | `shows_cursor_style()`, `async leave(...)`, `async enter(...)` and `async show(target, event)`. What viewers see of input; `InputVisualization` installs one. |
| `ActionChainPolicy` (`browserrig.tools`) | `async check(observe, tab) -> str`: empty allows continuing; otherwise explain why a fresh observation is required. Failed comparison ends the chain without turning successful input into failed input. |

`CaptureContent.fingerprint` is copied into the snapshot unchanged, including an
empty string. A strategy can use it to reflect changes its extracted DOM fields
cannot describe. When it is `None`, including with `DomCapture`, the runner keeps
deriving the existing fingerprint from the redacted page and document identity.

### References from other capture backends

`ElementInfo` holds target data without requiring a frame or DOM node ID.
`ElementRef(ref=...)` records an offscreen target. The existing `Element` and
`Offscreen` types extend those data with DOM addresses and remain supported.
`PageContent` is the shared page data container; the existing extraction module's
`Extraction` name remains an alias for it. DOM and non-DOM data can coexist in a
snapshot and survive JSON round trips.

A custom strategy returns `CaptureContent(page=PageContent(...), references=resolver)`.
Keep object bindings in that capture's resolver, not in reusable strategy configuration.
`resolve(tab, snapshot, ref)` receives the redacted published snapshot. Its handle's
`element.ref` must match the requested ref. Both resolution and location only read
state; location must check that the object still exists, is reachable and is not
covered, and must recompute its current viewport coordinates. A cached rectangle
alone does not establish that the target is still actionable.

Refs are opaque and must be unique within an observation, including offscreen refs.
Keep them stable for the same object and never reuse one for another object in the
same tab/document. The runner rejects duplicates. `Observe.element(tab, ref)` checks
the published membership and tab/document before resolving, then checks that the
observation and document did not change while awaiting resolution. A comparison
probe keeps its own resolver and never replaces the published snapshot or bindings.
`Observe.invalidate()` discards both together. Snapshots contain data only; runtime
resolvers stay in session state.

`DomElementHandle` supplies the additional DOM operations used by native form
tools: focus, select, value setting, upload and scripts. Those tools call
`Observe.dom_element(tab, ref)` and reject other handles before input, including in
mixed captures. Existing native select/date/upload behavior is preserved.
`KeyboardTools.type_text(ref, ...)` likewise requires a DOM handle; another backend
can use pointer tools to activate its target and `send_keys` to type through the
ordinary keyboard path. Select tool plugins explicitly for each integration.

Automatic reveal uses `ScrollableElement` when available. `ScrollStep.key` must
reflect progress in the plan; repeated unchanged keys stop a stalled scroll.
Handles without that optional contract locate visible targets, while the agent
can use normal scrolling or dragging to reveal more. DOM frame traversal and
scroll planning live in the DOM adapter, including nested and OOPIF transforms.

The default `DomActionChains` conservatively ends chains after input when a custom
resolver is installed. Hover checks still compare the custom fingerprint and
shared navigation/modal state before dispatching a click. Supply a fingerprint
that reflects relevant backend state, and a matching `Renderer` for its reference
instructions. A custom `ActionChainPolicy` can provide stronger continuation checks.

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
tasks. If the document changes while probing, the runner selects initial readiness
again for the new document within the original deadline. The standalone
`wait_for_page` API also restarts its probe on document changes. A policy factory
must create a new mutable probe each time.

For navigation dispatch, `Readiness.wait(..., dispatch=async_callback)` executes
the callback once inside the deadline. Dispatches are never deduplicated with
other commands or read-only waiters; cancelling their caller cancels their owned
wait. An exhausted report must be observed before a new dispatch is accepted.
A timeout cannot undo a navigation already sent to Chrome, so inspect the next
observation before retrying.

The default `ReadinessOptions` use a 7.5-second budget, a 300 ms quiet period,
750 ms minimum observation for initialization/navigation and 500 ms after input.
Polling normally runs every 100 ms. Quiet time before input does not count toward
the post-action quiet period. Adjust `action_min_ms` for applications with longer
delayed responses; no finite grace period can predict arbitrarily late timers.

The DOM policy checks main-frame navigation through `DOMContentLoaded`, DOM
mutations, scrolling, finite visible animations, visible `aria-busy` content and
accessible shadow/frame documents. Cross-origin frames use CDP sessions. Infinite
animations do not hold readiness indefinitely. Root/frame discovery is bounded;
incomplete inspection degrades rather than claiming readiness. DOM readiness does
not wait for every image, font or background network request.

`browser_plugins()` also mounts `DownloadReadiness()`. This separate plugin uses
`CheckReadiness`, so active downloads share the page's budget. Include it explicitly
in manual compositions when desired.

Default timeouts produce a `DEGRADED` report with `timed_out=True` and a reason.
Navigation tools include command dispatch in that deadline, so a slow response
before navigation commits cannot add a separate unbounded wait.
Successive action/comparison waits share the remaining budget until observation;
redirects never restart the clock. After a post-action timeout, the remaining
input chain stops and the following observation consumes the existing report
without another full wait.
It attempts a live capture for at most one additional second, falling back to a
loading observation with no stale refs or image if the renderer cannot answer.
The next model iteration can inspect the partial page and choose to wait. A later
readiness attempt gets a fresh budget. Set `allow_degraded_dom=False`, or return
`FAILED` from a custom strategy, for strict callers that require an exception.

A usable but continuously changing page can still accept deliberate input using
its delivered controls. A pending main-frame navigation or JavaScript dialog
blocks input; degradation alone does not permanently lock the agent out.

### Native readiness hooks

Application-specific conditions belong in plugins. For example, this plugin
selects a supplied policy for its application's URLs and adds an authoritative
busy signal around the default probe:

```python
from harnessed import Plugin, hook
from harnessed.hooks import Next
from browserrig import CheckReadiness, ReadinessCheck, SelectReadiness

class ApplicationReadiness(Plugin):
    def __init__(self, application, policy):
        super().__init__()
        self.application = application
        self.policy = policy

    @hook(SelectReadiness)
    def select(self, event: SelectReadiness):
        if self.application.matches(event.context.tab.url):
            return self.policy
        return None

    @hook(CheckReadiness)
    async def check(self, event: CheckReadiness, next_: Next[ReadinessCheck]):
        result = await next_()
        if result.ready and await self.application.is_busy(event.context.tab.id):
            return ReadinessCheck(False, "Application content is still loading")
        return result
```

`ReadinessContext.remaining` exposes the shared deadline to extensions. Hook
registration and removal follow the plugin mount. `Bail` and `Waterfall` requests
are in-process extension points; existing durable `ReadinessStartedEvent`,
`ReadyEvent`, `ReadinessDegradedEvent`, failure and cancellation events remain the
audit/stream receipts. Terminal receipts include `timed_out`; polling does not
flood the durable log with probe events.

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

`Agent` and `browser_plugins()` remain convenience recipes. A configured default
replaces the built-in one: `plugins=[Observe(capture=DomCapture(...),
screenshots=Screenshots(...)), Readiness(...), ImageContext(...), Actions(...),
InputPacing(motor)]`.
Pass `without=(FileTools,)` when local file tools should be omitted.

The default recipe mounts every tool group; ref-based tools hide themselves for
captures without refs. Transient availability (for example a missing workspace) still uses
tool gates, including execution-time rechecks. Existing upload path validation is retained.
Keep file readers as ordinary functions/strategies, not one plugin per file format.

For manual compositions, add `ImageContext()` explicitly: `Observe` no longer
injects images itself. Configure `Readiness` and `Observe` independently.
Harnessed filesystem tools can replace local file tools by passing
`without=(FileTools,)`; browser download paths are not automatically sandbox paths.
