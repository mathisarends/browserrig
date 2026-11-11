# Browser choreography

The presentation runs inside the active Chrome tab, so the live browser and
native recording show the same cursor, keyboard and action feedback. The design
follows the restrained palette, colored key groups and target corners of the
`browser-animations-demo` in Maximus Trading.

These are unaltered Chrome screenshots of the local walkthrough. Mouse and
keyboard input, scrolling, search, navigation, downloads, uploads and tab changes
use the browser APIs. The thinking example uses a scripted activity receipt;
the walkthrough makes no model requests.

![All presentation states](media/choreography/overview.png)

[Play the native Chrome recording](media/choreography/demo.mp4).
The MP4 contains the presentation in the browser's captured pixels. Real model-wait
intervals are cut by the recording plugin. The scripted thinking receipt in this
walkthrough demonstrates the appearance without making a model request.
Native browser toolbars are outside the recording; address and tab gestures use
temporary in-page indicators.

| Capture | Detail |
| --- | --- |
| [Pointer](media/choreography/pointer.png) | Named cursor, native hover and target corners. |
| [Keyboard](media/choreography/keyboard.png) | Complete German keyboard with native Ctrl+A. |
| [Scroll](media/choreography/scroll.png) | Direction and rotating wheel during native scrolling. |
| [Find](media/choreography/find.png) | Real page matches and the current result. |
| [Files](media/choreography/files.png) | Real download and native file upload. |
| [Navigation](media/choreography/navigation.png) | Address entry before navigation. |
| [Tabs](media/choreography/tabs.png) | Staged tab gesture before the native switch. |
| [Thinking](media/choreography/thinking.png) | Scripted model-activity receipt, shown live. |
| [Compact](media/choreography/compact.png) | Full keyboard at a 360-pixel viewport width. |
| [Observation](media/choreography/observation.png) | The same page captured without presentation pixels. |

## Reproduce

```console
uv run python -m examples.visualization --headed --layout de --theme dark
```

FFmpeg and a Chrome version supporting native Page recording must be available.
Omit `--headed` for a headless run. `--directory` changes the output directory;
`--layout en` and `--theme light` select the other appearance options.

The output includes individual PNGs, `overview.png`, `manifest.json`, the raw
recordings and timeline, and the edited `demo.mp4`. A local HTTP server serves
only the demonstration page, its download and the generated gallery.

## Configure

```python
from browserrig import IframeRenderer, InputVisualization

InputVisualization(
    renderer=IframeRenderer(
        name="Browserrig",
        keyboard_layout="de",
        theme="dark",
    )
)
```

`InputVisualization(renderer=None)` keeps the transient events for an external
viewer. The general `tab.overlays` API owns the iframe's identity, lifetime and
visibility. Perception and recording do not import choreography. Read the
[surface API and capture behavior](browser-composition.md#browser-owned-presentation)
for clean screenshots, cancellation handling and custom surfaces.

## Reading, results and activity

Work the pointer and keyboard cannot show plays where it happens on the page. A
single caption at the bottom names it in one line: an icon, a title, a short
detail and a state ring that turns into a check, warning or cross.

- **Reading a page** starts a soft beam, scrolls once to the loaded page's bottom,
  pauses briefly and returns to its original position before confirming the result.
  The extraction is saved before this presentation pass; newly lazy-loaded content
  does not silently enter the saved snapshot. The endpoint is fixed at the start,
  and reduced motion skips the scroll. The beam then narrows to the area
  that was actually read and dims the rest. Without `full_page` that is the main
  landmark, so a viewer sees that header and navigation were left out. A partial
  read ends with an amber edge where reading stops.
- **Screenshots** snap viewfinder corners onto the captured region with a brief
  flash; the caption icon becomes the thumbnail.
- **Reading files** keeps the normal cursor and uses its existing status label:
  `Reading report.pdf`. Successful reads need no extra card or file animation;
  warnings and failures still appear in the caption. Written files fly from the
  cursor into the caption.
- **Back, forward and reload** show a short card in the middle of the page with the
  direction and the host being left.
- **Failures** shake the cursor and show the reason in the caption.
- **Human handoff** outlines the viewport edge until control returns, and the
  cursor badge says the agent is waiting.

Page readiness is not shown; it is an implementation detail of every action.
Multiple downloads keep independent progress and completion cards. Preview text,
offsets, limitations and saved paths remain in the receipt for a Canvas detail
view; the inert overlay never renders them as HTML or takes pointer or keyboard
focus.

`extract_content` saves a Markdown snapshot and returns only a short file receipt.
Its latest successful full typed result is available as
`BrowserPerception.extracted_content`, including its saved path and actual
extraction limitations. File conversions keep their existing `.content/`
artifacts. A visible saved path always refers to an existing file, not a fictional
download created by the animation.

## Shared contract for browser and Canvas viewers

`InputVisualization` projects typed facts into `WorkPresentedEvent`
(`EventKind.WORK_PRESENTED`). It emits that same event whether the renderer is the
default iframe or `None`; result semantics are not inferred by the JavaScript view.
Existing cursor, keyboard, find, scrolling, tab and transfer events retain their
contracts. `ReadingSweepEvent` marks the native reading pass, keyed by `work_id`,
with `down`, `hold` and `back` durations in seconds. The work receipt completes
after the return; cancellation stops the pass and restores its scroll position.
Stream these together with activity and download events:

```python
from dataclasses import asdict

from browserrig.events import BrowserEvent, LiveEvent

# Start the consumer before session.run(). Subscriptions observe future events.
async for event in session.subscribe(transient=True):
    if isinstance(event, BrowserEvent | LiveEvent):
        await send_to_client(asdict(event))
```

Canvas consumers upsert work by `work_id`. `call_id` and `action_id` correlate tool
and browser execution; `kind` is `ActionKind`, or `None` for an unexecuted call whose
browser metadata was unavailable. `tool_name` identifies the original call.
`phase` is `WorkPhase`: `RUNNING`, `COMPLETED`, `WARNING`, `FAILED` or `CANCELLED`.
Running work remains until updated. A terminal receipt expires after `retention`
seconds; zero removes it immediately.

`title` and `detail` are ready to draw, while `source_path`, `source_url`,
`characters`, `offset`, `next_offset`, `page_number`, `page_count`, `content_status`,
`preview`, `limitations` and `artifact_path` provide structured result data.
`region` is a frozen `CaptureRegion(x, y, width, height)` in **source viewport CSS
pixels**: the captured area of a screenshot, or the visible area a page extraction read. Use `target_id` and `document_id` to choose the correct Canvas surface
and transform those coordinates into its displayed bounds. `image_url` contains
only the bounded screenshot thumbnail. Native download progress remains keyed by
`download_id`; show percentages only when total bytes are known.

Use the enum tags rather than parsing event-name prefixes. Python dispatch uses
event classes and enums; the iframe receives its tag tables from `EventKind`,
`WorkPhase`, `ActionKind` and `ActivityKind` rather than maintaining a second list of
wire names. A JSON schema for a frontend can be
generated with `TypeAdapter(WorkPresentedEvent).json_schema()` from Pydantic.

All new presentation receipts are transient: they stay out of model context, saved
session state and run results. Configured secrets are redacted **before** preview
truncation. Terminal logs omit rich preview text and screenshot data. The local view
keeps a bounded, typed receipt cache to restore active work and still-fresh results
after navigation, tab switches or a dialog; a Canvas viewer can retain that state
while its remote document changes. An open native dialog cannot render an iframe,
so its live presentation event lets the surrounding client display it immediately.
