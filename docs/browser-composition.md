# Compose a browser agent

[Back to README](../README.md)

Harnessed owns the agent loop. Browserrig adds independently configurable browser,
perception, action, context and presentation capabilities. Use `browserrig.Agent`
for the standard recipe. In a custom `harnessed.Agent`, list the plugins your
application needs at the composition root.

## Explicit plugin composition

Choose perception, context delivery and tools independently. The default recipe
assembles them for you; manual compositions expose every choice.

### Choose a recipe

Use the recipe and replace only what your agent needs:

```python
from browserrig import (
    Agent, BrowserPerception, Chrome, Choreography, ChoreographyOverlay,
    Screenshots, ScreenshotTrigger, TrimInBatches,
)

agent = Agent(
    model=model,
    browser=Chrome.connect(endpoint=endpoint),
    plugins=[
        BrowserPerception(
            screenshots=Screenshots(
                trigger=ScreenshotTrigger.EACH_STEP,
                retention=TrimInBatches(max_images=6, min_images=3),
            ),
        ),
    ],
    without=(Choreography, ChoreographyOverlay),
)
```

`model` and `endpoint` are application inputs. Matching plugin slots replace
recipe defaults in place; other plugins are added. `without` removes defaults by
type, and `None` entries are skipped. Two explicit plugins in the same slot raise
`PluginConflict`. `agent.describe()` shows the resolved composition without opening
Chrome.

### Compose a screenshot-driven single-tab agent

This prototype starts at the configured URL. It receives screenshots and uses
the pointer and keyboard to interact with the page.

```python
from harnessed import Agent
from browserrig import (
    Actions,
    BrowserPerception,
    Chrome,
    InputRuntime,
    KeyboardTools,
    PageReadiness,
    PointerTools,
    Runtime,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTrigger,
    SingleTab,
)

agent = Agent(
    model=model,
    plugins=[
        Runtime(),
        Chrome.launch(url="https://example.com"),
        InputRuntime(),
        PageReadiness(),
        SingleTab(),
        BrowserPerception(
            text=None,
            capture=ScreenshotCapture(),
            screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
        ),
        Actions(),
        PointerTools(),
        KeyboardTools(),
    ],
)
```

`Runtime`, `Chrome`, `InputRuntime` and `PageReadiness` provide the browser,
devices and readiness checks. `Actions` coordinates tool execution.
`PointerTools` uses screenshot coordinates and `KeyboardTools` sends keys to
the focused control.
`SingleTab` keeps the session in one tab. Add input pacing and viewer plugins
where the application needs them. Configure [Harnessed approvals](agent-guide.md#configure-an-agent)
for tools with side effects.

### Select tools for a DOM-driven agent

This agent uses text observations and exposes pointer, keyboard, navigation and
tab-management tools.

```python
from harnessed import Agent
from browserrig import (
    Actions, BrowserPerception, Chrome, InputRuntime, KeyboardTools, MultiTab,
    NavigationTools, PageReadiness, PointerTools, ReferencePointerTools, Runtime,
    TabTools, Targeting,
)

agent = Agent(
    model=model,
    plugins=[
        Runtime(), MultiTab(), Chrome.launch(), InputRuntime(), PageReadiness(),
        BrowserPerception(), Actions(), Targeting(),
        PointerTools(), ReferencePointerTools(), KeyboardTools(), NavigationTools(),
        TabTools(),
    ],
)
```

This composition has no workspace, presentation or task memory. Add capabilities
explicitly. `Actions()` observes after each input; the task recipe selects
`Actions(chain_policy=DomActionChains())` for verified DOM chains. Setup follows
service dependencies; instruction order follows the configured plugin list.
Configure Harnessed `Approvals` to allow tool side effects
or ask through your host UI.

## Offer wait independently of navigation

Import `WaitTools` from `browserrig` and mount it in a custom composition with
`Actions()` to offer a wait for asynchronous page updates. For example, add
`WaitTools(max_seconds=3)` to the screenshot-driven setup above.

`NavigationTools()` supplies a default `wait` tool. If you also mount
`WaitTools(max_seconds=..., description=...)`, its configuration takes
precedence. Removing that plugin restores navigation's default while
`NavigationTools` is mounted.

## Choose pointer tools

`PointerTools()` provides `click_at`, `drag_at` and `move_mouse(x, y)`. It
uses screenshot or viewport geometry and works with `ScreenshotCapture()`
without `Targeting()`.

Add `Targeting()` and `ReferencePointerTools()` for `click(ref)`,
`drag(source_ref, target_ref)` and `hover(ref)`. These tools work with
`DomCapture()` and [custom capture backends](#references-from-other-capture-backends)
that resolve their own refs.

`browserrig.Agent` includes both pointer plugins. For a screenshot-only
configuration of the standard agent, pass `without=(ReferencePointerTools,)`
with your screenshot perception.

## Choose tab behavior

The default recipe selects `MultiTab()`. Replace it at the composition root:

```python
from browserrig import Agent, Chrome, SingleTab

agent = Agent(
    model=model,
    browser=Chrome.launch(url="https://example.com"),
    plugins=[SingleTab()],
)
```

`SingleTab()` and `MultiTab()` share the `browserrig.tabs` slot. Two explicit
choices conflict. Manual Harnessed compositions can select either plugin too;
the browser backend retains multi-tab behavior when no policy is supplied.

Single-tab sessions reuse their controlled tab for navigation and file previews.
Ordinary links with new-window targets, forms (including POST), and simple
`window.open(url)` requests navigate in the controlled tab's top-level document.
History remains available. Redirected `window.open` calls return `null`; flows
that need a separate window handle, such as opening an empty popup to populate
later, are unsupported. Unexpected extra controlled tabs are
closed and reported instead of replaying their URL as a new request. Existing
tabs outside an attached session's scope are left alone.

Single-tab mode hides the tab-management tools and omits the tab overview from
observations and probes. Its fixed instructions describe single-tab navigation;
multi-tab guidance comes from `MultiTab()`. The current tab's internal identity
is retained for input, references and observation coherence. `TabStrip()` remains
an independent viewer feature in either mode.

With `SingleTab()`, the `navigate`, `click` and `click_at` tool schemas omit
`new_tab`. Tool calls that explicitly supply it are rejected before browser input,
even if the supplied value is `False`. `MultiTab()` exposes the parameter with
its usual default of `False`. These schemas are selected when the tools activate.

## Co-locate tools, instructions, hooks and state

A feature lives in one plugin. This example remembers research sources and makes
them available to subsequent model requests:

```python
from dataclasses import dataclass, field

from harnessed import Instructions, Plugin, PluginState, SystemPrompt, hook, tool
from harnessed.hooks import Next, PrepareRequest
from harnessed.kernel import needs
from harnessed.models import ModelRequest, UserMessage

from browserrig import Browser


@dataclass
class SourceState:
    urls: list[str] = field(default_factory=list)


class Sources(Plugin):
    _browser = needs(Browser)
    _state = PluginState(SourceState)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(Instructions(
            title="Research sources",
            text="Use remember_source to keep pages you intend to cite.",
        ))

    @tool(description="Remember the current page as a research source.", readonly=True)
    async def remember_source(self) -> str:
        url = self._browser.active_tab.url
        if url not in self._state.urls:
            self._state.urls.append(url)
        return f"Remembered: {url}"

    @hook(PrepareRequest)
    async def add_sources(
        self, event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        if not self._state.urls:
            return request
        return request.append_message(UserMessage(
            "Remembered source URLs:\n" + "\n".join(self._state.urls)
        ))
```

Add `Sources()` to the agent's `plugins` list. Its tool declaration, fixed guidance,
request middleware and state stay together. `await next_()` preserves the other
request hooks; the appended message affects only that request. The list survives
turns within the mounted session, but this example does not persist it across
session restoration. `PluginState` provides activation-local state, not storage.

Constructors hold reusable configuration. Acquire resources in
`async setup(self, scope: PluginScope)` with `scope.enter(...)`, and register cleanup
with `scope.effect(...)`. Compose plugins in the application or a `PluginPack`.

## How context propagates

| Context | Propagation and lifetime |
| --- | --- |
| Shared services | A provider calls `scope.provide(T, value)`. `needs(T)` binds required services; `observes(T)` binds optional ones. Both are resolved before setup and rebind through activation restart when providers change. |
| Call dependencies | `Inject[T]` parameters resolve for each tool or hook call. Declare required service dependencies with `needs(T)` too; use explicit `Inject[ToolContext]` for tool context. |
| Plugin state | `PluginState(factory)` creates mutable state for each activation. Reusing a recipe across sessions does not share this state. |
| Browser action | `Runtime()` provides `ActionContext` and `BrowserCoordination`. `Actions` fixes the addressed tab; devices and the backend read the same task-local action ID. Correlation expires when the operation ends. |
| Model context | `instructions()` supplies fixed guidance. `PrepareRequest` transforms the current request. `session.append_message(UserMessage(...))` adds durable conversation input. |
| Observations | `BrowserPerception` captures snapshots and projects text and images through `ProjectObservation`. `ObservationsIncludedEvent` confirms final inclusion after request hooks and compaction, so coordinates follow what the model actually saw. |

Application code resolves mounted services through `session.scope[T]`; plugins use
`PluginScope` and the restricted `SessionContext`. `BrowserCoordination` serializes
actions, observations, extraction and human handoff. Wrap a complete direct-input
operation in `coordination.exclusive()` when mixing it with agent work.

## Hooks you can use

| Hook | Contract | Typical use |
| --- | --- | --- |
| `PreStep` | Waterfall returning `StepDecision` | Capture or prepare state before the next model step |
| `PrepareRequest` | Waterfall returning `ModelRequest` | Add current application facts or transform request content |
| `ExecuteTool` / `ReviewToolResult` | Waterfall returning `ToolResult` | Wrap execution or inspect the converted result |
| `BrowserToolCall` | Waterfall returning the tool body's result | Extend browser execution before result conversion |
| `CheckAction` | Emit before a managed action starts | Reject an action when application state has changed or [record receipt fields](telemetry.md#add-receipt-attributes-from-a-plugin) |
| `ProjectObservation` | Waterfall returning `UserMessage` or `None` | Compose context from one immutable, redacted snapshot |
| `ChangeTab` | Waterfall around a tab operation | Synchronize devices or stage a transition |
| `SelectReadiness` | Bail: first non-`None` policy wins | Choose readiness for a page or application |
| `CheckReadiness` | Waterfall returning `ReadinessCheck` | Add a condition around a readiness probe |
| `Perform` | Waterfall around an intent's step | Stage navigation, page search, wait, preview or upload work |
| `TargetLocated` | Event | Highlight a resolved input target |
| `ObservationsIncludedEvent` | Event | Track the final observations sent to the model |

Import runtime hooks and `Next` from `harnessed.hooks`, observation inclusion from
`harnessed.events`, `ChangeTab` and readiness hooks from `browserrig`,
`ProjectObservation` from `browserrig.observation`, and tool/intent hooks from
`browserrig.tools`. Waterfall middleware calls `await next_()` to compose with the
remaining handlers. Registrations are removed with their mounting scope. Typed
[stream events](files-and-events.md#event-streams) report outcomes to applications;
in-process hook requests are separate extension points.

For example, an application can add its own readiness signal:

```python
from harnessed import Plugin, hook
from harnessed.hooks import Next
from browserrig import CheckReadiness, ReadinessCheck


class ApplicationReadiness(Plugin):
    def __init__(self, application):
        super().__init__()
        self.application = application

    @hook(CheckReadiness)
    async def check(self, event: CheckReadiness, next_: Next[ReadinessCheck]):
        result = await next_()
        if result.ready and await self.application.is_busy(event.context.tab.id):
            return ReadinessCheck(False, "Application content is still loading")
        return result
```

The application's check shares `event.context.remaining` with the page's readiness
deadline. `PageReadiness(initial=..., ongoing=...)` selects policies for a new document
and later operations. The default `NetworkQuiet()` combines DOM readiness with
bounded waits for requests caused by input/navigation. `DownloadReadiness()` adds
download checks independently. Timeouts normally produce a degraded observation
so the agent can inspect partial state and decide whether to wait.

### Validate an action before dispatch

Provide an `AppState` session service when the application has its own target
identity, coordinate layout, or input availability. A plugin can declare
`provides=AppState`. To also expose its concrete class, use `provides=True` and
call `scope.provide(AppState, self)` during setup.

- `generation(tab)` returns a `Generation` with hashable `state` and `layout`
  values. Browserrig stamps both onto observations and images alongside the DOM
  generation. A state change invalidates targets. A layout change invalidates
  coordinate actions. Use scalar values and tuples for JSON snapshot round trips.
- `blocked(tab)` returns a reason when the app cannot accept input, or `None`.
  Readiness reports the reason with status `BLOCKED`. Pass `app_state` to
  `wait_for_page` when calling it outside the session's `PageReadiness` service.

Register `@hook(CheckAction)` to validate managed `@browser_tool` actions and
explicit `Actions.run(...)` calls. The hook receives the addressed tab, action
kind, observation snapshot, and coordinate source in context when available.
Browserrig runs it once after generation validation and any per-call
`Actions.run(check=...)` check, while holding the action lock. Harnessed awaits
all registered checks in order. Keep checks read-only and use the addressed tab.

```python
from harnessed import Plugin, hook
from browserrig.core import BrowserError
from browserrig.tools import CheckAction


class ApplicationActionChecks(Plugin):
    def __init__(self, application):
        super().__init__()
        self.application = application

    @hook(CheckAction)
    async def check(self, action: CheckAction) -> None:
        if not await self.application.allows_action(action.tab, action.kind):
            raise BrowserError("The page changed. Inspect a fresh observation.")
```

A rejected action reports `ActionFailedEvent(dispatched=False)`. The runner emits
`ActionStartedEvent` and enters the operation only after validation succeeds.

## Add a browser tool

Declare browser semantics and let `Actions` coordinate execution. This example
uses the target recheck in `Targeting.hover` to require a stable target:

```python
from harnessed import Plugin
from harnessed.kernel import needs
from browserrig import ActionKind, Targeting
from browserrig.tools import Effect, browser_tool


class StableHoverTools(Plugin):
    _targeting = needs(Targeting)

    @browser_tool(
        kind=ActionKind.HOVER,
        description="Hover and verify that the target remains under the cursor.",
    )
    async def hover_stable(self, ref: str) -> Effect:
        point = await self._targeting.hover(ref=ref)
        return Effect("Hovered.", prepared_scroll=point.scrolled)
```

`browser_tool` requires an async function. Its `ActionKind` selects serialization,
input preparation, action receipts and readiness. The tool body performs its
operation directly; it does not acquire the coordination lock or call `Actions.run`
again. Mounted direct calls use their owner's scope too. Model-requested calls
also pass through Harnessed policy and approval checks. Trusted application code
can manage an operation explicitly with `Actions.run(...)`.

## References from other capture backends

| Contract | Implement |
| --- | --- |
| `CaptureStrategy` | `supports_dom_refs: ClassVar[bool]` and `collect(tab, report, *, screenshots, region=None, zoom=1, cursor=None) -> CaptureContent` |
| `Renderer` | `render(snapshot)`, `instructions()` and `refs()` |
| `References` | `async resolve(tab, snapshot, ref) -> ElementHandle` |
| `ElementHandle` | `element: ElementInfo`; `async locate(*, aim=None) -> ElementPoint` |
| `ReadinessPolicy` | `create(context) -> ReadinessStrategy`, with a fresh mutable probe per wait |
| `ImageRetention` | `overflow(count) -> int`, the number of oldest images to drop |

Return `CaptureContent(page=PageContent(...), references=resolver)` from a custom
capture. Keep bindings in that capture's resolver. Refs are opaque, unique within
an observation and stable for the same object; never reuse one for a different
object in the same document. Location must validate the live target, visibility
and hit testing, returning current viewport CSS coordinates. A cached rectangle
alone is insufficient. `RevealableElement` optionally performs backend-owned
reveal; `ScrollableElement` provides a wheel plan for devices to execute.
DOM reveal scrolls exact containers and reports measured movement.

`PageContent.content` can carry a reading tree of `ContentGroup`, `TextBlock`,
`Heading` and `ElementRef`; leaving it unset retains flat rendering. A custom
`fingerprint` supports change comparisons. `BrowserPerception` provides the callable
`ResolveDomElement` when the capture declares `supports_dom_refs = True`. The built-in
`DomCapture` declares it. A custom capture can inherit `CaptureStrategy` for
the default `False` or declare the class variable itself. When the service is
available, `await scope[ResolveDomElement](tab, ref)` returns a DOM handle.
Native forms, `DomUploadTools` and `DomTypingTools` use this service; other backends can use
pointer input and focused `send_keys`. `DomActionChains` conservatively ends input chains with
custom resolvers; supply a matching policy for stronger continuation checks.

Custom browser providers publish `Browser`, `BrowserEvents` and `InputTargets`.
`Runtime` owns coordination and action correlation; `InputRuntime` owns devices.
The input package has no browser/CDP dependency. Custom input backends can supply
`InputTargets` independently of `Browser`. File transfers use a separate
[`FileBridge`](files-and-events.md#workspaces-bridges-and-remote-browsers).

## Browser observations

`BrowserPerception` can deliver page text, a compact metadata header, screenshots,
or text with screenshots. Set `text=None` to omit text. Omit `screenshots` to
deliver text alone.

### Page text

`TextObservations()` sends page text as deltas when an earlier observation is
still in context. Use `mode="full"` to send full text on every step. The default
page capture is `DomCapture()`. Captures that support DOM refs use `DomRenderer()`
by default. Supply a renderer for page text with another capture strategy.

```python
from browserrig import BrowserPerception, DomCapture, Screenshots, TextObservations

perception = BrowserPerception(
    capture=DomCapture(page_prose="sparse"),
    text=TextObservations(mode="delta"),
    screenshots=Screenshots(),
)
```

### Metadata

Use `TextObservations(content="metadata", mode="full")` to send a compact page
header with every observation. It includes the title, URL, current tab,
controlled-tab count, and main-page scroll position and
remaining distance in CSS pixels. With a new screenshot, the header and image
are parts of the same message.

```python
from browserrig import BrowserPerception, Screenshots, TextObservations

perception = BrowserPerception(
    text=TextObservations(content="metadata", mode="full"),
    screenshots=Screenshots(),
)
```

Metadata text defaults to `ScreenshotCapture()`. Omit `screenshots` for
metadata alone. This path uses Chrome's layout metrics and skips DOM extraction.
Explicit captures and renderers can still be supplied. With `mode="delta"`, a
retained unchanged header can be reused when there is no new image.

### Capture with application services

A capture strategy passed as `capture=` is reusable configuration. When capture
needs a mount-local service, such as an application runtime, provide the strategy
from a plugin instead. `BrowserPerception` observes `CaptureStrategy`, uses a
provided strategy in place of its default and validates it during setup.
Configure the renderer on `BrowserPerception`, because system instructions are
read before setup.

```python
from harnessed import Plugin
from harnessed.kernel import PluginScope, needs

from browserrig import BrowserPerception, CaptureStrategy, TextObservations


class CanvasView(Plugin):
    _runtime = needs(CanvasRuntime)

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(CaptureStrategy, CanvasCapture(self._runtime))


plugins = [
    BrowserPerception(text=TextObservations(mode="full"), renderer=CanvasRenderer()),
    CanvasRuntime(),
    CanvasView(),
]
```

Setup fails when `capture=` is also configured.

### Screenshot settings

Capture timing, image retention and text compaction are independent:

| Setting | Behavior |
| --- | --- |
| `Screenshots(trigger=ScreenshotTrigger.ON_REQUEST)` | Default. Capture after a screenshot request. Image-only and metadata-and-image sessions also capture when they enter a document or lack an included image. |
| `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` | Capture before every model step |
| `Screenshots()` | Keep the latest image; unchanged captures are skipped |
| `Screenshots(retention=TrimInBatches(max_images=6, min_images=3))` | On overflow, trim oldest images down to three |
| `Screenshots(retention=UntilCompaction())` | Retain images until compaction removes their steps; requires compaction to bound history |

For image-only pixel capture, select `ScreenshotCapture()` with `text=None` and a
`Screenshots` configuration. To avoid DOM readiness probes, set both readiness
policies to `NetworkQuiet(inner=BrowserReady())`. For screenshots with ref labels,
configure `Screenshots(marks=SetOfMarks())` with `DomCapture()`, including when
the text mode is metadata.

Add `ScreenshotTools()` to offer explicit requests in a session configured
with screenshots. The tool acknowledges the request. The next observation
supplies the new image, reports reuse when unchanged, or reports why no image
was available.

Text observations remain until compaction. Coordinate tools use the latest
included screenshot's geometry; an image from another document cannot supply
coordinates for this page.

### Optional observation and DOM tools

Perception itself registers no model tools. Add `PageSearchTools()` for page
search. `DomTypingTools`, `DomScrollTools`, `FormTools` and `DomUploadTools`
provide separate DOM capabilities. Tools that take DOM refs require
`ResolveDomElement`. These plugins log at debug level when the service is missing.
`DomScrollTools` also provides `scroll_page`, which works without DOM refs.

## Browser-owned presentation

`InputPacing` installs a `Motor` controlling keystrokes, pointer routes and wheel
steps. Without it, `Instant` dispatches a wheel gesture in one event without a
pause. `HumanMotor` supplies a smooth wheel plan; use
`InputPacing(HumanMotor(scroll_speed=0.5))` for half the default scroll speed
(`HumanMotor` is imported from `browserrig.input`). Custom motors implement
`wheel_steps(delta_x=..., delta_y=...)`, returning `WheelStep` values with native
CSS-pixel deltas and `delay_before_seconds`. Their deltas must total the requested
distance; the mouse executes their timing without selecting its own scroll curve.
`Choreography` installs a `Presenter` controlling viewer feedback and streams it
as events; `ChoreographyOverlay` draws them in the page. All are optional;
tools consume the session's `Input` service in any configuration.
`InputRuntime` uses `ChangeTab` to synchronize devices; backend tabs own only
technical tab operations.

Application surfaces belong to the browser:

```python
overlay = await tab.overlays.mount(html="<p>Research in progress</p>")
await overlay.send({"type": "application.status", "text": "Ready"})
await overlay.close()
```

Surfaces are inert and pointer-transparent. Extraction and ordinary screenshots
omit them; `screenshot(tab, overlays=True)` explicitly includes them. Recording
coordinates with the browser's capture events without importing choreography.
See [choreography and video](browser-choreography.md) for viewer configuration.

Optional capabilities include [domain guards](agent-guide.md#navigation-and-secrets),
[human handoff](human-handoff.md), [workspace tools](files-and-events.md),
[task memory](task-memory.md) and [todos](todos.md).
