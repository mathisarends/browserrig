# Browser interaction

[Back to README](../README.md) · [Composition](browser-composition.md)

## Direct browser access

Use Chrome without a model inside an async function:

```python
from browserrig import ChromeBrowser, Input, Point, wait_for_page
from browserrig.browser import Launch
from browserrig.scripts import PAGE_FACTS

async with ChromeBrowser(Launch(url="https://example.com")) as browser:
    tab = browser.active_tab
    await wait_for_page(tab)
    frame = await tab.main_frame()
    print((await frame.run(PAGE_FACTS)).title)

    devices = Input(browser.input_targets.focused)
    await devices.mouse.resume()
    await devices.mouse.move_to(Point(x=100, y=120))
```

The browser owns tabs and CDP transport; `Input` owns devices. Direct callers
synchronize devices after technical tab changes. Agent sessions get that wiring
from `Runtime()` and `InputRuntime()` and resolve devices with `session.scope[Input]`.

Catch `browserrig.core.BrowserError` for CDP failures surfaced by `Tab`, `Frame`,
the browser screenshot helper and observation capture. The original cdpify
exception is available as `__cause__` on translated errors. Direct
`tab.cdp` and `frame.cdp` calls can raise cdpify exceptions.
When mixing direct inputs with agent work, acquire
`session.scope[BrowserCoordination].exclusive()` around the complete operation.

Runnable examples:

```powershell
uv run python -m examples.direct_browser --url https://example.com
uv run python -m examples.connect_browser --endpoint http://127.0.0.1:9222
```

`Chrome.launch(...)` owns a new process; `Chrome.connect(...)` leaves the external
browser running on exit. Connecting normally creates an isolated context;
`target_id=...` attaches to an existing tab and preserves its download policy.
Set `executable=` or `BROWSERRIG_CHROME` to choose Chrome explicitly.

For CDP setup, pass `session_setup=(setup, ...)`. Each
`SessionSetup.apply(cdp, *, frame)` runs after page/runtime initialization for a
new page or out-of-process frame session. Viewport configuration is applied first.

## Observations and element references

`BrowserPerception` delivers observations; the page model and image plugins
decide what they contain. `DomPage()` reads the DOM, including shadow roots and
nested/cross-origin frames, and `Screenshots()` adds viewport images. Select text
delivery with `BrowserPerception(text="delta")`, `"full"` or `None`.

```text
# Checkout
url: https://shop.example/checkout
in viewport:
  [MAIN]
    text: Read [delivery terms][59] before continuing.
    [48] textbox "Email" required
    [51] combobox "Country" options=[Germany*, France]
    [60] button "Continue"
```

Pass refs such as `48` or `f1:93` to element tools. Refs identify objects in the
current document; removed elements fail as stale. A leading `*` marks a newly
observed control. Text and controls follow document reading order. Observations
include nearby previews up to 1,000 CSS pixels beyond the viewport; set
`viewport_expansion=0` for a strict viewport. Hidden, inert and clipped content is
excluded. Cookie-banner detection is heuristic and makes no consent choice.

DOM text observations list controls with their labels. `DomPage` adds the
rest explicitly:

```python
DomPage(
    prose="inline",  # prose beside controls, or "sparse" / "off"
    max_text_chars=3000,
    headings=True,  # lines such as `## Pricing`
    landmarks=True,  # regions such as [MAIN] grouping their controls
)
```

`prose="sparse"` adds prose only when the viewport shows fewer than five named
controls; `search_page` still reads all text when prose is off. Dialogs and
cookie banners stay grouped. `max_elements=...` bounds controls. Use
`SetOfMarks()` to label controls in screenshots and `CursorMarker()` to draw
the cursor. Unsupported frames and
extraction limits are reported.
Perspective-transformed frames remain unsupported.

Custom page models supply opaque refs through `References`. `ReferencePointerTools`
and `ReferenceDragTools` resolve their live positions. DOM-specific typing and forms
require `ResolveDomElement`.
See [custom page models](browser-composition.md#custom-page-models).

## Input tools

| Capability | Tools and behavior |
| --- | --- |
| `PointerTools` | `click_at(x, y)` and `move_mouse(x, y)` by viewport or image coordinates |
| `ReferencePointerTools` | `click(ref, count=2)` and `hover(ref)` by observed element refs |
| `PointerDragTools` | `drag_at(start, end)` by viewport or image coordinates |
| `ReferenceDragTools` | `drag(source_ref, target_ref)` by observed element refs |
| `KeyboardTools` | `send_keys(text="Hello")` types text; `send_keys(key="Enter")` presses a key; modifier flags apply to keys |
| `DomTypingTools` | `type_text(ref, text, clear=True)` focuses and replaces a DOM field; `clear=False` inserts at its selection |
| `DomScrollTools` | `scroll_page(delta_y=..., delta_x=...)` moves the document; `scroll_element(ref=..., ...)` moves only that container |
| `FormTools` | Native selects, exact multi-select sets and date fields |
| `NavigationTools` / `TabTools` | Navigation, search, history and tab management |
| `WaitTools` | `wait(seconds=...)` for an expected asynchronous update, also supplied by default with navigation |
| `ScreenshotTools` | Request an image/crop at the next observation boundary |
| `PageSearchTools` | Search loaded page text for matching records |

Ref-based input reveals and hit-tests the target before acting. DOM reveal
scrolls exact containers, respecting overflow locks and embedding frames, and
reports actual movement. Custom backends can provide reveal or wheel plans.
Page/container scroll tools report their own movement without moving the cursor.

`click(..., button="right")` sends a native right click. `new_tab=True` opens a
link with the platform modifier; newly opened tabs become active. Drag endpoints
must fit together before the gesture begins. Held keys/buttons are released on
failure or cancellation. Text-field focus is checked while typing; a lost focus
can leave a prefix entered, so inspect before retrying.

`select_options(ref="123", values=["General", "Wholesale"])` replaces a native
multi-select's complete set; `values=[]` clears it. Values or displayed labels
must identify options unambiguously. Invalid or disabled changes reject the
whole request before mutation; the tool verifies the selected set afterward.
Observation values, radio IDs and `selection_group` are raw page metadata.

## Coordinates and resizing

Coordinates use viewport CSS pixels unless mapped from a screenshot included in
the model request. Text-only steps retain the latest included image's geometry.
Browserrig checks the source against the current tab, document, viewport and
tracked layout. After browserrig scrolls or otherwise invalidates that layout,
call `screenshot` if available and use the next delivered image. In a text-only
session, use the next observation's viewport coordinates.

Headed windows can be resized; headless launches pin viewport metrics. A resize
invalidates previous coordinates. Ref actions resolve their targets in the live
layout as long as the observed state still matches. A custom application can
expose its own state and layout changes through
[`AppState`](browser-composition.md#validate-an-action-before-dispatch).
Model screenshots omit application overlays by default.

## Page content and search

`search_page(query, alternatives=(), full_page=False, start=0, max_results=20)`
searches the loaded page text without scrolling or changing it, ignoring case and
accents. It returns whole records: table rows under their column header, innermost
list items and paragraphs, grouped by section heading and with their links. The
first line gives the total; continue with `start` when more records match. Searches
are read-only, so several can run in one response. It reads loaded DOM content,
including available shadow and frame documents, but does not load lazy content or
read canvas pixels. Hidden text, scripts and form values are omitted, and secrets are
redacted before matching. To collect findings across pages, write them to workspace
notes. The Python helper `browserrig.observation.content.extract_content(tab, ...)`
returns the page as typed Markdown.

## JavaScript

`execute_javascript(code=...)` evaluates in the active tab's main context, supports
top-level `await`, and keeps variables until navigation. Return plain objects for
JSON results. `timeout_seconds` defaults to 10, with a maximum of 30; pending
asynchronous effects can outlive a timeout. Inspect the page before retrying.
`Secrets` and `AllowedDomains` disable this tool while mounted.

Direct callers use `await tab.evaluate(...)`, `tab.go_back()`, `tab.go_forward()`
and `browser.tabs.list/open/activate/close`. Bare backend operations do not add
agent action coordination, device synchronization or presentation.

## Input choreography

`InputPacing` chooses how devices move, scroll and type; `Choreography` chooses how
people see that activity and `ChoreographyOverlay` draws it in the page. All three
are optional and independently configurable.
`devices.pace(motor)` and `devices.present(presenter)` return callbacks restoring
the previous implementations. `Perform`, `TargetLocated` and `ChangeTab` provide
hooks around intents, resolved targets and tab operations.

Input receipts carry browser/tab/document identity and the current action ID.
Viewers consume transient cursor, keyboard, scroll and work events; durable
receipts record browser outcomes. See [events](files-and-events.md#event-streams)
and the [choreography gallery](browser-choreography.md).
