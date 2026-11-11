# Compose a browser agent

[Back to README](../README.md)

Harnessed owns the agent loop. Browserrig adds independently configurable browser,
perception, action, context and presentation capabilities. `browserrig.Agent` is a
recipe; `browser_pack()` exposes that recipe to a Harnessed `Agent`. Both use the
same plugins and service contracts.

## Explicit plugin composition

Choose perception, context delivery and tools independently. The default recipe
assembles them for you; manual compositions expose every choice.

### Choose a recipe

Use the recipe and replace only what your agent needs:

```python
from browserrig import (
    Agent, Chrome, DomCapture, DomPerception, ImageContext,
    InputVisualization, Screenshots, ScreenshotTrigger, TrimInBatches,
)

agent = Agent(
    model=model,
    browser=Chrome.connect(endpoint=endpoint),
    plugins=[
        DomPerception(
            capture=DomCapture(marks=False),
            screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
        ),
        ImageContext(TrimInBatches(max_images=6, min_images=3)),
    ],
    without=(InputVisualization,),
)
```

`model` and `endpoint` are application inputs. Matching plugin slots replace
recipe defaults in place; other plugins are added. `without` removes defaults by
type, and `None` entries are skipped. Two explicit plugins in the same slot raise
`PluginConflict`. `agent.describe()` shows the resolved composition without opening
Chrome.

To compose inside an existing Harnessed application:

```python
from harnessed import Agent
from browserrig import Chrome, browser_pack

agent = Agent(
    model=model,
    plugins=[browser_pack(browser=Chrome.launch(url="https://example.com")), Sources()],
)
```

`Sources` is defined below. `browser_plugins(...)` returns a resolved flat list
when needed. For a fully explicit composition, select individual plugins:

```python
from harnessed import Agent
from browserrig import (
    Actions, Chrome, DomPerception, ImageContext, InputRuntime, KeyboardTools,
    NavigationTools, PointerTools, Readiness, Runtime, TabTools, Targeting,
    TextContext,
)

agent = Agent(
    model=model,
    plugins=[
        Runtime(), Chrome.launch(), InputRuntime(), Readiness(), DomPerception(),
        TextContext(), ImageContext(), Actions(), Targeting(),
        PointerTools(), KeyboardTools(), NavigationTools(), TabTools(),
    ],
)
```

This composition has no workspace, presentation or task memory. Add capabilities
explicitly. `Actions()` observes after each input; the task recipe selects
`Actions(chain_policy=DomActionChains())` for verified DOM chains. Setup follows
service dependencies; instruction order follows the configured plugin list.
Configure Harnessed `Approvals` to allow tool side effects
or ask through your host UI.

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

Mount `Sources()` alongside the browser pack. Its tool declaration, fixed guidance,
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
| Observations | `BrowserPerception` captures snapshots; `TextContext` and `ImageContext` project text and images through `ProjectObservation`. `ObservationsIncludedEvent` confirms final inclusion after request hooks and compaction, so coordinates follow what the model actually saw. |

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
| `ProjectObservation` | Waterfall returning `UserMessage` or `None` | Compose context from one immutable, redacted snapshot |
| `ChangeTab` | Waterfall around a tab operation | Synchronize devices or stage a transition |
| `SelectReadiness` | Bail: first non-`None` policy wins | Choose readiness for a page or application |
| `CheckReadiness` | Waterfall returning `ReadinessCheck` | Add a condition around a readiness probe |
| `Perform` | Waterfall around an intent's step | Stage navigation, find, wait, preview or upload work |
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
deadline. `Readiness(initial=..., ongoing=...)` selects policies for a new document
and later operations. The default `NetworkQuiet()` combines DOM readiness with
bounded waits for requests caused by input/navigation. `DownloadReadiness()` adds
download checks independently. Timeouts normally produce a degraded observation
so the agent can inspect partial state and decide whether to wait.

## Add a browser tool

Declare browser semantics and let `Actions` coordinate execution:

```python
from harnessed import Plugin
from harnessed.kernel import needs
from browserrig import ActionKind, Targeting
from browserrig.tools import Effect, browser_tool


class HoverTools(Plugin):
    _targeting = needs(Targeting)

    @browser_tool(
        kind=ActionKind.MOVE_MOUSE,
        description="Hover an observed element without clicking.",
    )
    async def hover_ref(self, ref: str) -> Effect:
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
| `CaptureStrategy` | `collect(tab, report, *, screenshots, region=None, zoom=1, cursor=None) -> CaptureContent` |
| `Renderer` | `render(snapshot)`, `instructions(screenshots)` and `refs()` |
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
`fingerprint` supports change comparisons. `DomPerception` provides `DomElements`
for native forms, `DomUploadTools` and `DomTypingTools`; other backends can use
pointer input and focused `send_keys`. `DomActionChains` conservatively ends input chains with
custom resolvers; supply a matching policy for stronger continuation checks.

Custom browser providers publish `Browser`, `BrowserEvents` and `InputTargets`.
`Runtime` owns coordination and action correlation; `InputRuntime` owns devices.
The input package has no browser/CDP dependency. Custom input backends can supply
`InputTargets` independently of `Browser`. File transfers use a separate
[`FileBridge`](files-and-events.md#workspaces-bridges-and-remote-browsers).

## Screenshot settings

Capture, image retention and text compaction are independent:

| Setting | Behavior |
| --- | --- |
| `Screenshots(trigger=ScreenshotTrigger.ON_REQUEST)` | Default: capture after the screenshot tool requests an image |
| `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` | Capture before every model step |
| `ImageContext()` | Keep the latest image; unchanged captures are skipped |
| `ImageContext(TrimInBatches(max_images=6, min_images=3))` | On overflow, trim oldest images down to three |
| `ImageContext(UntilCompaction())` | Retain images until compaction removes their steps; requires compaction to bound history |

Manual compositions select `TextContext(mode="delta")` or `mode="full"` for text
and `ImageContext()` for images. Image observations include matching full text.
Perception itself registers no model tools: add `ScreenshotTools()` for screenshot
requests and `PageExtractionTools()` plus a workspace for saved Markdown.
`DomTypingTools`, `DomScrollTools` and `FormTools` are separate DOM capabilities.
Without context plugins, capture does not publish browser observations.
Text observations remain until compaction. Coordinate tools use the latest
included screenshot's geometry; an image from another document cannot supply
coordinates for this page.

## Browser-owned presentation

`InputPacing` installs a `Motor` controlling keystrokes and pointer routes.
`InputVisualization` installs a `Presenter` controlling viewer feedback. Both are
optional; tools consume the session's `Input` service with either configuration.
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
