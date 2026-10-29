# Browserrig

Event-driven Chrome automation for AI agents and Python applications, built with
[Harnessed 0.2.0](https://github.com/mathisarends/harnessed/releases/tag/v0.2.0),
cdpify, and Pydantic. Harnessed is pinned exactly in `pyproject.toml` and `uv.lock`.
Browserrig combines direct browser access with composable agent plugins, explicit
DOM and canvas modes, and a shared event log.

- Launch Chrome or connect to a running browser through CDP.
- Work with explicitly addressed tabs and structured, validated page observations.
- Interact through DOM references or screenshot coordinates, including double-clicks and drags.
- Pause, steer, resume, stop, or abort agent sessions through Harnessed's native controls.
- Record browser activity and subscribe to typed events for actions and downloads.

## Quick start

From a checkout of this repository:

```powershell
uv sync --locked --extra openai
Copy-Item .env.example .env
# Set OPENAI_API_KEY in .env.
uv run --env-file .env --extra openai python -m examples.openai_agent --headed --record
```

The example mission explores the Voyager program: compare the missions, open
detail articles in new tabs, and find unusual contents of the Golden Record.
The default task and starting page are in German; use `--task` and `--url` to
override them, for example:

```powershell
uv run --env-file .env --extra openai python -m examples.openai_agent --headed --url https://en.wikipedia.org/wiki/Voyager_program --task "Compare Voyager 1 and 2 and cite the source URLs."
```

The OpenAI example streams structured JSON events to stderr while the agent runs.
Use `--quiet` to disable this output. The final answer is written to stdout.

The examples use `OpenAIResponsesModel` with `gpt-6.1-terra` by default.
Set `OPENAI_MODEL` to override the model ID. These examples use the Responses API
for tool calling. Tests use scripted models and do not require an API key.

## Direct browser access

Use the browser without an LLM inside an async function:

```python
from browserrig import ChromeBrowser, LaunchBrowser, wait_for_page

async with ChromeBrowser(LaunchBrowser(url="https://example.com")) as browser:
    tab = browser.active_tab
    await wait_for_page(browser, tab)
    print(await tab.evaluate("document.title"))
```

Runnable examples:

```powershell
uv run python -m examples.direct_browser --url https://example.com
uv run python -m examples.connect_browser --endpoint http://127.0.0.1:9222
```

Connecting creates an isolated context in the running browser. Use
`--target-id TARGET` to explicitly select an existing tab. The external browser
must already expose a CDP endpoint and stays running after disconnecting.

## BrowserAgent

`BrowserAgent` configures Harnessed's `Agent` with browser capabilities:

```python
from harnessed import PolicyDecision
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import BrowserAgent, LaunchBrowser, RecordingOptions, DomMode, TerminalEvents

agent = BrowserAgent(
    model=OpenAIResponsesModel("gpt-6.1-terra"),
    browser=LaunchBrowser(url="https://en.wikipedia.org/wiki/Voyager_program"),
    mode=DomMode(screenshots=True),
    recording=RecordingOptions(),
    session_directory=".browserrig/sessions-v2",
    approvals=Approvals(default=PolicyDecision.ALLOW),
    plugins=[TerminalEvents()],
)
result = await agent.run("Compare Voyager 1 and 2 and cite the source URLs.", max_steps=20)
print(result.text)
```

`run()`, `session()`, `sessions`, and session controls remain native Harnessed APIs.
Native Pydantic AI models are accepted directly; Harnessed enters and exits their
resource contexts. Explicitly supplied HTTP and provider SDK clients remain caller-owned.
Use `instructions=...` to replace the default instruction and `plugins=[...]` to
add capabilities. Conversations stay in memory unless `session_directory` is set.
Without explicit `approvals`, Harnessed's default `ASK` policy applies; the example
above allows actions automatically. The constructor does not open Chrome or files.

For custom composition, `browser_plugins()` returns an inspectable plugin list:
`Agent(model=model, plugins=[*browser_plugins(), MyPlugin()])`.
Individual capabilities such as `Chrome`, `Readiness`, `Observe`, `Actions`, tool
plugins, `Nudges`, `Activity`, `Recording`, and `TerminalEvents` are also available directly.
Shared plugin services use class-level `Inject[T]` and `provides=True`; required
injections infer dependencies. Optional services resolve on each hook invocation.
Tool decorators declare model-facing descriptions independently of developer docstrings.

## Upgrading existing sessions

Harnessed 0.2.0 requires session record format 2 and rejects format 1 without
automatic migration. Back up existing session stores and choose a fresh directory
when upgrading. The OpenAI example now writes to `.browserrig/sessions-v2`;
existing `.browserrig/sessions` files stay available in their original directory.
Custom `session_directory` values should also point to a fresh store. See the
[migration guide](https://github.com/mathisarends/harnessed/blob/v0.2.0/Changelog.md).

## Session controls and canvas mode

Inside an `async with agent.session() as session:` block:

```python
handle = await session.submit("Inspect this page.")
await session.pause()
await session.steer("Focus on the navigation.")
await session.context.set("constraints", "Do not submit forms.")
await session.resume()
result = await handle.result()
```

Pausing waits for a complete step boundary and leaves Chromium running.
`session.stop()` ends the session gracefully; `session.abort()` interrupts it
immediately. Resuming observes the current page again. Activity tracking uses
events rather than an LLM decorator.

```powershell
uv run --env-file .env --extra openai python -m examples.controls
uv run --env-file .env --extra openai python -m examples.figma_agent --url YOUR_URL --record
```

Canvas mode uses images and coordinates, with an initial check of geometry and
pixel content. DOM mode returns Pydantic-validated YAML with roles, labels, and
references tied to the current observation.

## Element references and screenshot marks

DOM mode includes an annotated screenshot by default. Numbered labels and colored
dashed borders identify interactive elements. Each label matches an element's
`mark` in the YAML; pass that element's full `ref`, such as `a1b2c3d4:7`, to
`click`, `type_text`, and other element tools. A mark is a visual lookup number;
the ref addresses the observed DOM node in its own frame. Both belong to the
latest observation and can change after observing again.

Links use blue borders, buttons green, text inputs purple, and selection controls
pink or orange. Marks follow document order within each frame. Screenshots use
viewport CSS pixels even on HiDPI displays. Annotations are drawn on the image
without changing the page. Use `DomMode(marks=False)` for plain screenshots or
`DomMode(screenshots=False)` for YAML only.

Extraction follows the composed DOM, including slots, open and closed shadow
roots, and CDP click-listener metadata. It checks viewport visibility, clipping,
and overlapping controls. Nested same-origin and cross-origin frames use their
own isolated worlds and CDP sessions where needed. Frame transforms account for
borders, scrolling, scaling, and rotation; ancestor hit tests reject covered
frames before clicking. Unreachable frames and content limits are reported in
`limitations`, while usable frames remain available. Frame discovery is bounded
to 64 frames and eight levels; perspective transforms are reported as unsupported.

## Double-clicks and dragging

`InteractionTools` provides `click(ref=..., count=2)` and
`drag(source_ref=..., target_ref=...)`. Both drag endpoints must be visible at
the same time; gestures do not scroll automatically. Native `draggable` elements
use HTML5 drag and drop with a real `DataTransfer`.

`PointerTools`, used in canvas mode, provides
`click_at(x=..., y=..., count=2)` and
`drag_at(start=Point(...), end=Point(...), mode=DragMode.POINTER)`.
Use `DragMode.HTML5` for coordinate-based dragging of native HTML5 sources.
The current observation determines how crop coordinates map to the viewport.
Both variants use real CDP input and release mouse buttons even when interrupted.

## Input choreography

Each tab owns its input state at `tab.input`. DOM and canvas tools share this
controller, with action serialization and readiness still owned by `Actions`.
Cursor movements follow bounded cubic paths; scrolling uses eased wheel steps.
Typing uses a fixed 50 ms interval, configured by the internal
`_TYPING_INTERVAL_SECONDS` constant in `browserrig/input/keyboard.py`.

`KeyboardTools` supplies `send_keys` in both modes. It addresses the current page
focus and takes exactly one of `text` or `key`:

- `send_keys(text="Hello world")` types literal text at the current selection.
- `send_keys(text="Enter")` types the word Enter.
- `send_keys(key="Enter")` presses Enter.
- `send_keys(key="Escape")` presses Escape.
- `send_keys(key="a", hold_control=True)` selects all text in the focused editor.
- `send_keys(key="Tab", hold_shift=True)` moves focus backwards.

`hold_control`, `hold_shift`, `hold_alt`, and `hold_meta` apply to `key`. All held
modifiers are released after the key. Literal text uses `text` without modifier flags.

In DOM mode, `FormTools` also supplies `type_text(ref=..., text=...)` to focus and
replace a referenced field. Use `clear=False` to type at its current selection.

Keys and modifiers are released on failure or cancellation. Unicode text is
dispatched once per character, without simulated typos. Empty replacement text
clears the field. Direct Python callers can use `tab.input.type_text(...)`,
`tab.input.press_key(...)`, `tab.input.move_to(Point(...))`, and
`tab.input.scroll(point=Point(...), delta_y=...)`. Acquire `browser.action_lock`
when combining direct inputs with other browser actions.

The choreography uses Harnessed's native transient event extension. `Chrome`
registers these frozen event types alongside its durable browser events:

| Event | Payload |
| --- | --- |
| `CursorMovedEvent` | Start, destination, two control points, duration, easing |
| `CursorStateEvent` | Actual cursor position and held mouse buttons |
| `PointerPressedEvent`, `PointerReleasedEvent` | Position and native click count |
| `KeyPressedEvent` | Key, modifiers, duration |
| `KeyboardVisibilityEvent` | Keyboard presentation opened or closed |
| `ScrolledEvent` | Wheel origin, dispatched deltas, duration |
| `ElementHighlightedEvent` | DOM reference and viewport bounds |
| `WaitingEvent` | Requested wait duration |

Coordinates use viewport CSS pixels; durations use seconds. Events carry
`browser_id`, `target_id`, `document_id`, and `at`. Inputs inside an action also
carry its `action_id`. `CursorMovedEvent` describes the path before execution;
`CursorStateEvent` reports the actual endpoint, including after cancellation.
Key and pointer receipts follow successful dispatch. Action failure events close
interrupted sequences. Key events contain the dispatched key and modifiers.

Navigation, tab changes, downloads, and model/tool/readiness/pause intervals keep
their existing typed events. Consumers can use those together with input events
to present the session's choreography. Transient input events are excluded from
`session.events`, JSONL storage, and model context; durable action receipts remain
available for replay.

`TerminalEvents()` prints one JSON object per event to stderr using native hooks,
without a background consumer task. It includes session lifecycle, model/tool
metadata, browser actions, and live input events. Prompts, tool arguments, model
output, and screenshots are omitted. Pass `TerminalEvents(output=file)` to select
another text stream.

## Recording, downloads, and events

Native recording uses `Page.startScreenRecording` / `stopScreenRecording` through
cdpify. Recordings under `.browserrig/recordings/` include segments and a validated
manifest with checksums, timing references, and periods spent waiting only for the
model. The media container is checked; ffmpeg is not a runtime dependency.
The manifest distinguishes canvas crops from native viewport recordings.

`LaunchBrowser(download_directory="ABSOLUTE_PATH_ON_BROWSER_HOST")` enables
downloads in the browser's own context. `DownloadState` includes `IN_PROGRESS`,
`COMPLETED`, and `CANCELED`; download events use the `browser.download.*` namespace.
Upload and download paths refer to the browser host.

Subscribe to durable facts and live choreography from a session while a run is
active (for example, from a consumer task started before `session.run`):

```python
from browserrig.events import ActionStartedEvent, CursorMovedEvent, KeyPressedEvent

async for event in session.subscribe(transient=True):
    match event:
        case ActionStartedEvent(kind=kind):
            print(kind)
        case CursorMovedEvent(to_position=point, duration=duration):
            print("cursor", point, duration)
        case KeyPressedEvent(key=key):
            print("key", key)
```

Subscriptions observe future events and finish when the session closes.
`session.subscribe()` without `transient=True` continues to return durable facts only.

Import SDK events directly from `harnessed.events`, for example
`ToolCallRequestedEvent` and `ToolCallFinishedEvent`. The latter carries the final
reviewed result, including denied calls. Activity intervals use execution receipts
for tool timing and the SDK's `request_id` for model timing, including failures,
cancellations, and context-limit retries. Tool cancellation and timeout have
separate activity outcomes.

Browser observations carry their snapshot ID in `Observation.refs`. Hints carry
their nudge IDs and are acknowledged only by `ObservationsIncludedEvent` for the
`browser.nudges` source in full form. Summaries and IDs appearing in ordinary text
leave hints queued. `NudgeIncludedEvent.request_id` matches the submitted request;
`SessionLog.included_observations(request)` exposes the durable provenance on replay.

## Development

Development tools require Python >=3.12, uv, and Node.js >=24.
Python sources live in `browserrig/`.

```powershell
uv sync --locked --extra openai
npm.cmd ci
uv run pre-commit install
uv run pre-commit run --all-files

uv run ruff check browserrig examples tests
uv run ruff format --check browserrig examples tests
uv run pylint browserrig examples tests
uv run ty check
npm.cmd run lint
npm.cmd run format:check
uv run pytest -m "not integration"
uv run pytest -m integration
uv build
```

Pre-commit hooks use the uv and npm dependencies pinned in the lockfiles.
On Linux and macOS, use `npm` instead of `npm.cmd` and `cp .env.example .env`
instead of `Copy-Item`.

JavaScript is checked with ESLint and Prettier: braces for every control block,
at most two nested blocks, and no nested ternary expressions. Pylint limits Python
blocks to three nesting levels; Ruff also checks for simplifications. CI runs the
same lint, formatting, and type checks. To format code, run
`uv run ruff format browserrig examples tests` and `npm.cmd run format`.

Integration tests require Chrome or Chromium. Set `BROWSERRIG_CHROME` or
`LaunchBrowser(executable=...)` to select the executable. Media validation also
uses ffprobe when available.

## Project status

The core is implemented and tested against real Chrome, including transformed,
nested, and out-of-process iframes (OOPIFs). Broader platform coverage, complex Figma
device-frame detection, perspective-transformed frames, and recovery from process
crashes remain areas for further validation.
