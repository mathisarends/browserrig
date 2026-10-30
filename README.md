# Browserrig

Event-driven Chrome automation for AI agents and Python applications, built with
[Harnessed 0.6.0](https://github.com/mathisarends/harnessed/releases/tag/v0.6.0),
cdpify, and Pydantic. Harnessed is pinned exactly in `pyproject.toml` and `uv.lock`.
Browserrig combines direct browser access with composable agent plugins, explicit
DOM and canvas modes, and a shared event log.

- Launch Chrome or connect to a running browser through CDP.
- Work with explicitly addressed tabs and structured, validated page observations.
- Interact through DOM references or screenshot coordinates, including double-clicks and drags.
- Pause, steer, resume, stop, or abort agent sessions through Harnessed's native controls.
- Record browser activity and subscribe to typed events for actions and downloads.
- Give agents a persistent workspace, read downloaded PDFs, and preview files in new tabs.

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
from browserrig.scripts import PAGE_FACTS

async with ChromeBrowser(LaunchBrowser(url="https://example.com")) as browser:
    tab = browser.active_tab
    await wait_for_page(tab)
    frame = await tab.main_frame()
    facts = await frame.run(PAGE_FACTS)
    print(facts.title)
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
    mode=DomMode(),
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
Use `system_prompt=...` to replace the default instruction and `plugins=[...]` to
add capabilities. Conversations stay in memory unless `session_directory` is set.
Without explicit `approvals`, Harnessed's default `ASK` policy applies; the example
above allows actions automatically. The constructor does not open Chrome or files.

For custom composition, `browser_plugins()` returns an inspectable plugin list:
`Agent(model=model, plugins=[*browser_plugins(), MyPlugin()])`.
Individual capabilities such as `Chrome`, `Readiness`, `Observe`, `Actions`, tool
plugins, `Nudges`, `Activity`, `Recording`, and `TerminalEvents` are also available directly.
See [composing browser agents](docs/browser-composition.md) for the explicit plugin API:
`Readiness(initial=..., ongoing=...)`, `Observe(capture=..., renderer=...,
screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP))` and
`ImageContext(TrimInBatches(max_images=6, min_images=3))` or
`ImageContext(UntilCompaction())`. Capture, rendering, image retention and
tool capabilities can be selected independently. `ScreenshotTrigger.ON_REQUEST`
captures only after a screenshot tool call. Existing mode options remain recipe adapters.
Shared plugin services use class-level `Inject[T]` and `provides=True`; explicit
`needs=(...)` declarations control waiting, teardown, and restart when a provider changes.
Injection binds values without inferring dependencies. Optional services resolve
on each hook invocation and remain optional unless explicitly listed in `needs`.
Tool decorators declare model-facing descriptions independently of developer docstrings.

## Action chains and stable tool kinds

Browserrig uses Harnessed's native scheduler for action chains. Deterministic
form filling can combine `type_text`, `select_option`, `set_date`, and a final
`click` in one model response. `send_keys` can also continue in DOM mode. File
reads/writes, listings and content extraction can be chained. Browser tools run
sequentially against explicitly addressed tabs.

Navigation, search, history, reload, tab changes, file previews, scrolling, drags,
coordinate actions, JavaScript, uploads, dialogs, waiting, `observe` and `screenshot`
use `ToolChain.STOP_AFTER`. The tool executes first; unstarted calls after it receive
`ToolStatus.SKIPPED`. The next model step can continue. Denied or disabled tools
retain Harnessed's native approval semantics and do not themselves stop the chain.

DOM inputs dynamically stop the chain after navigation, changed tabs, a changed
modal, a new alert, expanded controls or newly available interactive elements.
Typing that reveals suggestions retains the entered text and skips later calls.
Hover that reveals controls defers the original click and explicitly reports that
it was not dispatched. Ordinary value changes and cosmetic text updates do not
interrupt form filling. Comparison probes omit screenshots and preserve the
delivered observation, its element references and its new-element markers.
An incomplete or failed comparison stops the chain; it does not report successful
input as failed. Canvas inputs require another observation after each input.

Each built-in tool declares its own stable `ActionKind` through immutable
`BrowserToolMetadata`. Use `event.tool.metadata.get(BrowserToolMetadata)` in native
policy, execution or result-review hooks; the registration is captured when the
call is scheduled. Kinds are explicit constants, never derived from callback names
or signatures. In particular, `OPEN_TAB`, `SWITCH_TAB`, `CLOSE_TAB`, `LIST_TABS`,
`OPEN_FILE` and `OPEN_DOWNLOADED_FILE` are distinct. Coordinate clicks/drags and
DOM clicks/drags also have separate kinds. Existing semantic names `TYPE`, `PRESS`,
`SELECT`, `UPLOAD` and `JAVASCRIPT` identify their respective tools; date inputs use
`SET_DATE`. Click count remains an input parameter rather than changing tool kind.
Older `TAB` and `DOUBLE_CLICK` receipt values remain readable.

Import `ActionKind` from `browserrig.kinds` and `BrowserToolMetadata` or
`browser_tool` from `browserrig.tools`. The small `browser_tool` decorator requires
an explicit kind and defaults to ending the chain. Metadata stays process-local;
mutation receipts persist their stable action kind. `Actions.run()` returns the
native `ToolResult`, exposing both `.text` and `.break_chain` to direct callers.

## Step limits and optional final summaries

Configure Harnessed's native loop through the existing plugin interface:

```python
from harnessed.plugins import AgentLoop, FinalStepPolicy

agent = BrowserAgent(
    model=model,
    plugins=[AgentLoop(max_steps=20, final_step=FinalStepPolicy.SUMMARIZE)],
)
result = await agent.run("Investigate the page")
print(result.text)
```

This reserves the last available step for a text summary: a limit of 20 permits
at most 19 tool steps. Per-run `max_steps=` overrides determine the effective
limit. Summaries remain opt-in because they consume that allowance. A reserved
summary returns `completed=False` and `StopReason.MAX_STEPS`, and cannot execute
tools. For structured output, read `.text` on incomplete results; `.output` raises
`OutputUnavailable`. Native `PreStep` hooks expose `max_steps`, `remaining_steps`,
`is_last_step` and `is_final_step`; manually constructed events require `max_steps=`.

## System prompts and optional MCP tools

`BrowserAgent(system_prompt="...")` appends browser plugin sections automatically.
For titled Markdown or XML, pass a native `SystemPrompt`:

```python
from harnessed import PromptFormat, SystemPrompt
from browserrig import BrowserAgent

agent = BrowserAgent(
    system_prompt=SystemPrompt(
        format=PromptFormat.MARKDOWN,
        sections=("Complete the requested browser task using the observed page state.",),
    ),
)
print(agent.prompt)
```

`Observe` declares configuration-dependent `page_state` and `refs` sections, plus
the shared `trust` section. DOM guidance follows screenshot, mark and page-text
settings; canvas guidance describes image coordinates and omits DOM-ref rules.
`PointerTools.coordinates`, `ImageContext.usage` and `FileTools.usage` describe shared workflows.
Single-tool instructions live in tool descriptions.

With a custom `browser_plugins()` composition, use the configured recipes' section
attributes in `SystemPrompt(sections=..., exclude=...)` to reorder or replace
individual sections. `PluginSections()` places the remaining declarations.
For manual compositions, configure `Observe` independently of `Readiness` and add
`ImageContext()` to deliver captured images. The legacy mode argument is still
supported by both plugins, but readiness no longer implicitly selects capture.
Use `await session.prompt.render()` to inspect the exact session system text.

Plugins mounted through `session.use()` require an explicit choice when they declare
sections: `section_delivery=SectionDelivery.CONTEXT` delivers guidance until the
mount closes or suspends; `SectionDelivery.IGNORE` skips it. Import `SectionDelivery`
from `harnessed`. The fixed system prompt stays unchanged.

Install the optional MCP client with `uv sync --locked --extra openai --extra mcp`.
All Harnessed extras are pinned to **0.6.0**. Add MCP servers through the native plugin:

```python
from harnessed.plugins.mcp import MCP

agent = BrowserAgent(
    plugins=[MCP.http("catalog", url="http://localhost:8000/mcp", include_tools=["search"])],
)
```

`MCP.stdio("catalog", command=..., args=[...])` starts a local server instead.
Connections belong to each session, tool names are prefixed (for example
`catalog__search`), and existing approval policies apply. See the
[Harnessed MCP guide](https://github.com/mathisarends/harnessed/blob/v0.6.0/docs/guides/mcp.md).

Harnessed 0.6.0 closes failed MCP transports, hides their tools, wakes pending
calls and drains owned tasks. Failed operations are not retried automatically;
replace a failed connection with a fresh mount. Ordinary tool `isError` results
keep the connection usable. HTTP termination has a five-second inactivity timeout.

## Plugin validation and diagnostics

Browser plugins declare their required services explicitly, including dependencies
used only by tool or hook parameters. Custom plugins must do the same:

```python
from harnessed import Inject, Plugin
from browserrig import Browser


class Extension(Plugin, needs=(Browser,)):
    browser: Inject[Browser]
```

`BrowserAgent` keeps Harnessed's strict startup validation by default. Missing
services raise `PluginDependencyError` from `harnessed.errors` before the runtime
starts, including through `run()`. Its `.issues` tuple identifies each waiting
plugin through `.plugin` and its missing service keys through `.missing`.

For plugins deliberately waiting for services added later, pass
`plugin_validation=PluginValidation.WARN` to `BrowserAgent`, importing
`PluginValidation` from `harnessed`. This emits `PluginDependencyWarning` with the
same structured issues and retains waiting plugins for later activation; setup
failures still propagate. Add services through native `session.use()` as usual.
For standalone kernel compositions, call `await ctx.settle()` followed by
`ctx.plugin_diagnostics()` to inspect waiting plugins, including blocked dependents.

## Upgrading existing sessions

Harnessed 0.6.0 keeps session record format 2: existing 0.2.0 through 0.5.0 stores can be reused
without migration. When upgrading from 0.1.0, format 1 is rejected without automatic
migration. Back up those stores and choose a fresh directory. The OpenAI example
writes to `.browserrig/sessions-v2`;
existing `.browserrig/sessions` files stay available in their original directory.
Custom `session_directory` values containing format 1 should also point to a fresh
store. See the
[migration guide](https://github.com/mathisarends/harnessed/blob/v0.6.0/Changelog.md).

Version 0.5.0 adds defaulted fields to model requests, turn starts and tool results.
Strict application schemas must accept those fields, `break_chain` and
`ToolStatus.SKIPPED`; older Harnessed readers may reject new records.

When upgrading application code from 0.3.0, rename `BrowserAgent(instructions=...)`
to `BrowserAgent(system_prompt=...)`; wrap instruction lists in
`SystemPrompt(sections=(...))`. Replace custom plugin `guidance` attributes with
`SystemSection` or synchronous `@system_section` declarations. New recipes mount
`PointerTools` for coordinates and `DomTools` for ref-based mouse, typing and forms.
`MouseTools` remains a compatibility group; do not mount overlapping tool groups.
Canvas recipes omit DOM tools instead of installing disabled tools.

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
pixel content. DOM mode returns compact line-based text with roles, labels, states
and stable element refs.

## Element references and screenshot marks

DOM mode reads every frame document with one `DOMSnapshot.captureSnapshot` call per
CDP session and derives roles, names, states, visibility and landmark sections from
that data in Python, without walking the DOM in the page. Normal observations omit
page-text excerpts and do not capture new screenshots. Use `extract_content()`
to read the page. The agent can call `screenshot()` to request the current view as an
image in its next iteration. `ImageContext` keeps the latest screenshot by default,
including during subsequent text-only steps. `observe()` refreshes page state. Use
`DomMode(screenshots=True)` to enable images on every step; canvas mode includes
images automatically. `DomMode(max_text_chars=N)` enables a page-text excerpt; its
default is `0`.

An observation looks like this:

```text
# Checkout
url: https://shop.example/checkout
tab: 3F2A9C...
viewport: 1280x800, scroll 0 of 2400px (0.0 pages above, 2.0 below)
modal: dialog "Cookie settings" is open; interact with it first

in viewport:
  [HEADER]
    [12] link "Cart" -> /cart
  [MAIN]
    ## Shipping address
    <form "Shipping">
      [48] textbox "Email" required placeholder="you@example.com"
      [51] combobox "Country" options=[Germany*, France, Spain]
      *[57] checkbox "Save address" unchecked
    [60] button "Continue"
```

Only the elements and headings inside the viewport are listed and described; the
header's scroll position says how much of the page lies above and below, and the
agent scrolls to see more. A leading
`*` marks elements that were not in the previous observation of the same document. There is no default element-count limit;
`DomMode(max_elements=N)` keeps the elements nearest to the viewport and reports
the truncation. Hidden, inert and fully clipped controls are omitted. Controls behind
a positioned overlay are reported as covered and are not listed individually.

Refs such as `482` or `f1:93` are CDP backend node ids, prefixed for out-of-process
frames. They stay valid across observations as long as the element stays in the same
document, and an action on a removed element fails with a stale-element error. Pass
the ref to `click`, `type_text` and other element tools.

Requested DOM screenshots draw a labeled, colored dashed border around every element
in the viewport; each label is the element's ref. Links use blue borders, buttons
green, text inputs purple, and selection controls pink or orange. Screenshots use
viewport CSS pixels even on HiDPI displays. Annotations are drawn on the image
without changing the page. Use `DomMode(marks=False)` for plain screenshots.

Extraction follows the composed DOM, including slots, open and closed shadow roots,
and CDP click-listener metadata. It checks viewport visibility, clipping and
overlays without scrolling during observation. Nested same-origin and cross-origin
frames use their own CDP sessions where needed. Frame transforms account for
borders, scrolling, scaling and rotation; ancestor hit tests reject covered frames
before clicking. Unreachable frames and content limits are reported as `note:`
lines, while usable frames remain available. Frame discovery is bounded to 64
frames and eight levels; perspective transforms are reported as unsupported.

## JavaScript shell and forward navigation

`execute_javascript(code="1 + 1")` runs JavaScript through CDP's `Runtime.evaluate`
in the active tab's main page context. It is available in DOM and canvas mode.
The tool returns the last expression's value, supports top-level `await`, and keeps
variables between calls until the page navigates. Use `await` for Promise results.
Return plain objects and arrays
for JSON results; `undefined`, `NaN`, infinities, and BigInts retain their JavaScript
representation. JavaScript exceptions and execution timeouts become tool errors.
`timeout` is in seconds, defaults to 10, and accepts up to 30. A timeout can leave
asynchronous side effects pending; observe the page before retrying.

```javascript
const heading = document.querySelector('h1');
({ title: document.title, heading: heading?.textContent });
```

`go_forward()` navigates to the next browser history entry, complementing
`go_back()`. Its tool result confirms `Navigated forward.` or reports
`Cannot go forward: no next history entry` when no forward navigation is possible.

Direct Python callers can use `await tab.evaluate("1 + 1")` for a rendered result,
`await tab.can_go_forward()` to check availability, and `await tab.go_forward()`
for a boolean indicating whether a history navigation was dispatched. Agent tools
use the shared action lock, readiness checks, and action receipts.

## Page content as Markdown

The agent can call `extract_content(max_chars=50000)` to read the active page as
structured Markdown. The result includes the page title and source URL, headings,
paragraphs, emphasis, lists, links with absolute URLs, tables, quotes, and code.
It reads already loaded content below the viewport without scrolling, navigating,
or invalidating the current element references. Open and closed shadow roots and
available same-origin and cross-origin frame documents are included.

`max_chars` limits the Markdown body (1–200000 characters); the title, source URL,
and extraction limitations are reported separately. Truncation, unavailable DOM
metadata, and unavailable frames are explicit. Offscreen rendered frame documents
are included. Scripts, styles, hidden content, and form field values are excluded.
Lazy content must already be
loaded; images contribute their alt text, and canvas pixels are not converted to
text. Use `screenshot()` when visual inspection is needed.

## Double-clicks and dragging

DOM interactions prepare the target's viewport automatically with native, eased
wheel input, including horizontal scrolling, nested scroll containers, and parent
frames. Comfortable targets stay in place. Near-edge and offscreen targets are
positioned with a 12% comfort margin and a preferred vertical anchor around one
third of the viewport; fitting form groups and labels are kept together. Fixed
and pinned sticky controls do not trigger document scrolling. Coordinates and
ancestor hit tests are refreshed after scrolling and before dispatching input.
Typing, selecting options, setting date inputs, and uploads use this preparation
as well as clicks. Focus uses `preventScroll` to avoid an extra browser jump.

`DomTools` provides `click(ref=..., count=2)` and
`drag(source_ref=..., target_ref=...)`. Both drag endpoints are prepared first and
must fit in the viewport together before the gesture starts. Native `draggable`
elements use HTML5 drag and drop with a real `DataTransfer`.

In both DOM and canvas mode, `PointerTools` provides `move_mouse(x=..., y=...)`,
`scroll(delta_y=...)`,
`click_at(x=..., y=..., count=2)` and
`drag_at(start=Point(...), end=Point(...), mode=DragMode.POINTER)`.
Use `DragMode.HTML5` for coordinate-based dragging of native HTML5 sources.
`move_mouse` moves the cursor without clicking and can reveal hover controls.
`scroll` sends wheel input at the current cursor position: move over a sidebar,
panel, or other scrollable area first to scroll that area.
Both `click` and `click_at` accept `button="right"` for a native right click;
the default is `button="left"`. Both tools automatically move the cursor to the
target before clicking. Right clicks end the action chain so the agent can
inspect the result before continuing.
`wait(seconds=...)` pauses for 0–10 seconds (default: 1) and emits a transient
`WaitingEvent` (`browser.waiting`) before the pause, with its requested duration,
browser, tab, and document IDs for live UI display.
The newest image shown to the model determines how crop coordinates map to the viewport;
subsequent text-only observations retain that image's geometry.
DOM and canvas screenshots include a red cursor arrow at the pointer position at
capture time, with its tip at the exact input coordinate. The marker follows
crop and zoom coordinates and is omitted when the pointer is outside the image.
It is drawn with Pillow after capture; canvas change detection uses the image
without the marker.
All gestures use real CDP input and release mouse buttons even when interrupted.
Canvas recipes do not install DOM-ref tools. Workspace tools are hidden when a connected browser has
no shared local file system; `list_downloads` remains available.

## Input choreography

Each tab exposes separate `tab.mouse` and `tab.keyboard` controllers, also
available as `tab.input.mouse` and `tab.input.keyboard`. `tab.input` shares the
action context and event correlation across both devices. DOM and canvas tools
use these same controllers; `Actions` owns action serialization and readiness.
New tabs initialize the native cursor at a random position within the central
40–60% of the actual viewport on each axis and immediately emit
`browser.cursor.state`. There is no initial animation from the top-left corner.
Activating an existing tab republishes its current position. Agent turn starts
also publish the current cursor state so live subscribers attached after browser
setup can display it before the first model request or input action.
Low-level pointer dispatch uses `MouseEventKind`, available from `browserrig` or
`browserrig.kinds`: `await tab.mouse.dispatch(MouseEventKind.MOVED, Point(x=100, y=120))`.
The enum also provides `PRESSED`, `RELEASED`, and `WHEEL`; use `scroll()` for wheel input.
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

For DOM input, `DomTools` supplies `type_text(ref=..., text=...)` to focus and
replace a referenced field. Use `clear=False` to type at its current selection.

Keys and modifiers are released on failure or cancellation. Unicode text is
dispatched once per character, without simulated typos. Empty replacement text
clears the field. Direct Python callers can use `tab.keyboard.type_text(...)`,
`tab.keyboard.press_key(...)`, `tab.mouse.move_to(Point(...))`, and
`tab.mouse.scroll(point=Point(...), delta_y=...)`. Acquire `browser.action_lock`
when combining direct inputs with other browser actions.

The choreography uses Harnessed's native transient event extension. `Chrome`
registers these frozen event types alongside its durable browser events:

| Event | Payload |
| --- | --- |
| `CursorMovedEvent` | Start, destination, two control points, duration, easing |
| `CursorStateEvent` | Actual cursor position and held mouse buttons |
| `CursorStyleEvent` | CSS cursor under the pointer (`CursorStyle`, such as `pointer` or `text`) |
| `PointerPressedEvent`, `PointerReleasedEvent` | Position, mouse button and native click count |
| `KeyPressedEvent` | Key, modifiers, duration |
| `KeyboardVisibilityEvent` | Keyboard presentation opened or closed |
| `ScrolledEvent` | Wheel origin, dispatched deltas, duration |
| `HighlightElementEvent` | DOM reference and viewport bounds |
| `WaitingEvent` | Requested wait duration |
| `FileTransferEvent` | `open` or `upload`, file paths, duration and the upload target point |
| `DownloadProgressedEvent` | Download ID, received bytes and total bytes when known |

Coordinates use viewport CSS pixels; durations use seconds. Events carry
`browser_id`, `target_id`, `document_id`, and `at`. Inputs inside an action also
carry its `action_id`. `CursorMovedEvent` describes the path before execution;
`CursorStateEvent` reports the actual endpoint, including after cancellation.
Key and pointer receipts follow successful dispatch. Action failure events close
interrupted sequences. Key events contain the dispatched key and modifiers.

The harness paces its choreography: events with a `duration` describe an
animation the browser waits through before continuing. `open_file` and
`open_downloaded_file` emit a `FileTransferEvent` in the current tab, wait for it,
and only then open the new tab. Uploads move the cursor onto the file input, emit
the transfer with that point, wait, and then assign the files.
`CursorStyleEvent` follows cursor movement and scrolling and is only emitted when
the style changes. It reads the page's computed CSS cursor and treats text inputs,
editable content and plain text as `text`; custom cursor images show `default`.
The probe is best-effort and never delays input by more than 250 ms.
`DownloadProgressedEvent` is sent at most every 200 ms per download; completion,
failure and cancellation remain durable events.

Navigation, tab changes, downloads, and model/tool/readiness/pause intervals keep
their existing typed events. Consumers can use those together with input events
to present the session's choreography. Transient input events are excluded from
`session.events`, JSONL storage, and model context; durable action receipts remain
available for replay.

`TerminalEvents()` prints one JSON object per event to stderr using native hooks,
without a background consumer task. It includes session lifecycle, model/tool
metadata, browser actions, live input events, correlated compaction attempts and
typed model retry activity. Tool records include `tool_status` and `break_chain`.
Retry records retain `request_id`, `retry_group_id` and `retry_kind`; unknown
attempt/retry counters remain JSON `null`. Provider attempts, context recovery and
output correction have separate scopes. Prompts, tool arguments, model
output, and screenshots are omitted. Pass `TerminalEvents(output=file)` to select
another text stream.
Page text, dialog messages and form value fields are omitted; URLs, filenames and
dispatched key names remain diagnostic metadata.

## Recording, downloads, and events

Native recording uses `Page.startScreenRecording` / `stopScreenRecording` through
cdpify. Recordings under `.browserrig/recordings/` include segments and a validated
manifest with checksums, timing references, and periods spent waiting only for the
model. The media container is checked; ffmpeg is not a runtime dependency.
The manifest distinguishes canvas crops from native viewport recordings.
Lost segments are reported by `RecordingSegmentLostEvent` and the manifest's
`lost_segments` field. Recording can continue on later tabs after a tab closes or
a segment exceeds `max_bytes`; partial files are removed. `required=True` treats
backend start failures as fatal.

Launched browsers automatically get a workspace under `.browserrig/files/<unique-id>/`
and save downloads in its `downloads/` directory. Files remain available after the
browser closes. Choose a reusable workspace explicitly:

```python
from pathlib import Path
from browserrig import BrowserAgent, FileSystemOptions, LaunchBrowser

agent = BrowserAgent(
    model=model,
    browser=LaunchBrowser(url="https://example.com"),
    file_system=FileSystemOptions(directory=Path(".browserrig/research")),
)
```

`file_system` is also accepted by `browser_plugins()`, `Chrome`, and `ChromeBrowser`.
The constructor creates no files or directories; browser startup creates the directories.
File access is confined to the workspace and any explicitly configured download
directory, including checks for path traversal and symlinks leaving those roots.

The agent sees the workspace and its latest 20 downloads before every step.
File tools are available in both DOM and canvas modes:

| Tool | Behavior |
| --- | --- |
| `list_files(path=".", offset=0, limit=100)` | List a directory; follow `next_offset` for more. |
| `read_file(path, page_number=None, sheet=None, cell_range=None, member=None, ocr=None, offset=0, max_chars=20000)` | Read native document content, worksheet cells, archive members or OCR text. Returns structure, limitations, a saved extraction path and continuation offsets. |
| `write_file(path, content, overwrite=False)` | Save UTF-8 text and create parent directories; overwriting requires an explicit flag. |
| `list_downloads()` | List download IDs, status, saved paths, and file errors. |
| `open_downloaded_file(download_id)` | Open a completed download in a new active tab. |
| `open_file(path)` | Open a workspace/download file in a new active tab. |

Pass paths returned by `list_files` or `list_downloads`, or paths relative to the
workspace. The normal installation (`uv sync --locked`) includes all file readers
and local CPU OCR; no separate parser extras, browser preview or screenshots are
needed to read supported content.

| Format | Content and selection |
| --- | --- |
| Text, Markdown, source code, JSON, XML, YAML, logs, subtitles | Text with encoding detection and character offsets. |
| CSV, TSV; XLSX/XLSM/XLTX/XLTM, XLS, ODS | Worksheet names and cell addresses; choose `sheet` and an A1 `cell_range`. XLSX includes formulas, stored results, number formats, merged and hidden ranges. |
| PDF | One page, defaulting to page 1; `page_count` exposes the remaining pages. Pages without native text use local OCR automatically. `ocr=True` explicitly requests full-page OCR; `ocr=False` disables it. |
| PNG, JPEG, TIFF, GIF, BMP, WEBP, ICO | Image metadata and local OCR text; `page_number` selects a frame in a multi-frame image. |
| DOCX, PPTX, ODT, ODP, RTF | Document text and tables; PPTX also exposes speaker notes and optional slide selection with `page_number`. |
| HTML/XHTML/SVG, MHTML, EPUB | Readable text; EPUB follows chapter order. Embedded images and document-specific resources have explicit limitations. |
| ZIP, TAR and compressed TAR; GZ, BZ2, XZ; EML, MBOX | Entry or attachment listings. Select `member="report.xlsx"`, `member="#1"`, or nested `member="bundle.zip!/report.xlsx"`; the same readers process the selected content. |
| SQLite | Table names and values; select a table with `sheet`. Binary BLOBs are identified by size. |
| Audio and video | Metadata only; no transcription or video understanding. |

`max_chars` limits each response, independently of the saved extraction. Converted
content is saved under the workspace's `.content/` directory and returned as
`extracted_path`. It contains the full selected page, sheet, range, member or
document, including extraction limitations. Follow `next_offset` with the same
selection to continue, or read `extracted_path` as text. Plain text streams directly
from the original file. Changing the source invalidates its derived cache.

`status` distinguishes `complete`, `partial`, `metadata_only` and `unsupported`;
`limitations` identifies missing content. Office graphics, comments and annotations
are not fully represented. OCR can make recognition and reading-order errors.
Formulas are never recalculated and stored results may be stale. Source files
are preserved; macros and scripts are not executed. Legacy DOC/PPT, XLSB, MSG,
7Z/RAR, iWork, MOBI/AZW and specialized binary datasets currently report missing
reader support explicitly.

`max_file_bytes` defaults to 50 MB for document parser inputs and writes; plain
text reads stream beyond that size. `max_expanded_bytes` defaults to 200 MB and
`max_archive_depth` to 8. Exceeding a processing bound raises an explicit error.
Very large or sparse XLSX sheets expose a bounded initial view with a limitation
and support targeted `cell_range` reads elsewhere in the sheet. These processing
bounds are separate from response pagination.

File tools report facts as durable `browser.files.*` events, registered by
`FileTools` (`FILE_EVENTS`) and `UploadTools` (`UPLOAD_EVENTS`). Presentation,
such as a file drawer, is left to the viewer:

| Event | Emitted by | Payload |
| --- | --- | --- |
| `FilesListedEvent` | `list_files` | Directory, entry count and pagination offsets |
| `FileReadStartedEvent` | `read_file` | `read_id`, requested path and selectors |
| `FileReadFinishedEvent` | `read_file` | `read_id`, path, format, status, character count, pages and offsets |
| `FileReadFailedEvent` | `read_file` | `read_id`, requested path and reason, including cancellation |
| `FileWrittenEvent` | `write_file` | Path, size and whether the file was created |
| `FileOpenedEvent` | `open_file`, `open_downloaded_file` | Path, `FileSource` and download ID; `target_id` is the new tab |
| `FilesUploadedEvent` | `upload_files` | Paths and the file input reference |

Reads can take seconds for OCR or large documents; `read_id` pairs the start with
exactly one finished or failed event.

`open_file` and `open_downloaded_file` remain available for a visual preview.
`switch_tab` returns to the original page. DOM uploads through
`UploadTools.upload_files` accept workspace-relative paths or absolute paths
returned by file tools. Every selected file must exist within the workspace or
configured download directory; the whole selection is checked before browser
input. Uploads are disabled without a shared local filesystem, including remote
browsers without explicit `FileSystemOptions`. Stage external files in the workspace
from application code before asking the agent to upload them.

Direct Python callers can use `browser.files.read_file(path, page_number=2)` and
`await browser.open_tab(browser.files.resolve(path))`; `open_tab` opens a `Path`
as a local file and only accepts HTTP(S) URLs as strings. Filesystem methods are synchronous; use
`asyncio.to_thread` when processing files inside an async application.

### File access boundaries and optional sandboxes

Browserrig's built-in file tools confine reads, writes, listings, previews and
uploads to the configured workspace and download directory. Path traversal and
symlinks resolving outside those roots are rejected. Browserrig does not expose
a shell tool. Keep the workspace dedicated to agent files; anything placed in it
is available to the agent.

This is a tool-level path policy. Chrome, document parsers, custom Python plugins
and MCP servers still run with their process permissions. Concurrent host changes
to links or directories are outside this boundary. Application calls such as
`ChromeBrowser.open_tab(Path(...))` and `Frame.upload_files(...)` remain trusted
host APIs. Use a separate OS/container boundary when the whole browser or parser
process must be isolated.

Harnessed 0.6.0 also supports a filesystem-only runtime sandbox: compose
`DockerSandbox(...)` or `BubblewrapSandbox(...)` with `FilesystemTools()` and omit
`ShellTools()`. The shell service is then not exposed as a model tool. This is
opt-in and requires an application-managed Docker image or Linux rootfs; startup
failure never falls back to host execution. See the
[sandbox guide](https://github.com/mathisarends/harnessed/blob/v0.6.0/docs/guides/sandboxes.md).

These backends do not redirect Browserrig's local `FileTools`, uploads, Chrome
downloads or document readers. In a custom composition, omit Browserrig's
`FileTools` and `UploadTools` before adding `FilesystemTools` to avoid duplicate
tool names and host file access through those tools. Transfer files explicitly
from application code; copied sandbox results must be exported before session
close. Browserrig does not implement Harnessed's `FileSystemBackend` protocol, so
the new `read_bytes`/`grep` backend contract needs no migration here.

The file reader uses a shared `FileExtension` enum and a registry of readers with
a common call signature and declared selection capabilities. New formats can be
registered without extending a central parser dispatch chain. See
[the validation report](file-reader-validation.md) for real-document coverage and
the command to repeat the public corpus check.

`LaunchBrowser(download_directory="ABSOLUTE_PATH_ON_BROWSER_HOST")` overrides the
download location. Downloads first use `.pending/` and then move into a folder
named by their stable download ID, preserving their filename and extension.
Duplicate filenames get separate folders. `DownloadState` includes `IN_PROGRESS`,
`COMPLETED`, and `CANCELED`; download events use the `browser.download.*` namespace.
`Download.total_bytes` is `None` when the server does not announce a size.
Canceled downloads emit `DownloadCanceledEvent` instead of `DownloadFailedEvent`.

Connected browsers keep their existing host semantics: `ConnectBrowser` enables
workspace tools only when `file_system=FileSystemOptions(...)` explicitly identifies
a directory shared with the browser host at the same absolute path. Without it,
download tracking still works but local file reads and previews are unavailable.
Attaching to an existing `target_id` retains its browser-wide download policy.
The OpenAI example accepts `--workspace .browserrig/research` to reuse a directory.

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

Compaction intervals use their own `compaction_id` and distinguish applied,
discarded, failed and cancelled attempts. They do not close an outstanding model
request. Live model attempts and compaction notifications are transient and are
not replayed. Applied compactions remain durable native history events.
`session.stream()` forwards native model request/failure, attempt/retry and
compaction activity. A request, attempt or compaction finishing does not finish
the turn; use `TurnFinishedEvent.result` on normal stream exhaustion and release
live UI activity in `finally` on cancellation or stream failure.

Browser observations carry their snapshot ID in `Observation.refs`. Hints carry
their nudge IDs and are acknowledged only by `ObservationsIncludedEvent` for the
`browser.nudges` source in full form. Summaries and IDs appearing in ordinary text
leave hints queued. `NudgeIncludedEvent.request_id` matches the submitted request;
`SessionLog.included_observations(request)` exposes the durable provenance on replay.

## Development

Development tools require Python >=3.12, uv, and Node.js >=24.
Python sources live in `browserrig/`.

Keep public entry points before private helpers in modules, and public methods before
private methods in classes. Imports and prerequisite type or constant declarations come
first; preserve definition-time dependencies used by defaults, decorators and registries.
Apply this order to production code, tests and examples.

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
uv run pytest                  # unit tests only (default)
uv run pytest -m integration   # real Chrome; `-m ""` runs everything
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
