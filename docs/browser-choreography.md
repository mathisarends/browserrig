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

InputVisualization(renderer=IframeRenderer(
    name="Browserrig", keyboard_layout="de", theme="dark",
))
```

`InputVisualization(renderer=None)` keeps the transient events for an external
viewer. The general `tab.overlays` API owns the iframe's identity, lifetime and
visibility. Perception and recording do not import choreography. Read the
[surface API and capture behavior](browser-composition.md#browser-owned-presentation)
for clean screenshots, cancellation handling and custom surfaces.

## Reading, results and activity

The overlay also shows file reads and writes, directory/download/tab listings,
page extraction, JavaScript, screenshot requests and captures, history navigation,
reloads, native selection/date changes, dialogs, page readiness and human handoff.
Failures, cancellation and calls denied or skipped before execution get terminal
receipts. Multiple downloads retain independent progress and completion cards.

Work cards show a bounded text preview, selection/page counts, continuation offsets,
extraction limitations and an actual saved path when one exists. Screenshot requests
remain pending until perception captures the next observation; completion carries
a small inline JPEG and its source viewport region. Preview text never becomes HTML.
The overlay remains inert: previews show their first lines without taking pointer
or keyboard focus. An interactive client can use the same payload for a detail view.

`extract_content` still returns Markdown without writing a workspace file. Its latest
successful typed result is available as `BrowserPerception.extracted_content`, with
`next_offset` and `partial` metadata. File conversions keep their existing `.content/`
artifacts. A visible saved path always refers to an existing file, not a fictional
download created by the animation.

## Shared contract for browser and Canvas viewers

`InputVisualization` projects typed facts into `WorkPresentedEvent`
(`EventKind.WORK_PRESENTED`). It emits that same event whether the renderer is the
default iframe or `None`; result semantics are not inferred by the JavaScript view.
Existing cursor, keyboard, find, scrolling, tab and transfer events retain their
contracts. Stream them together with activity and download events:

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
seconds; zero removes it immediately, as with successful readiness checks.

`title` and `detail` are ready to draw, while `source_path`, `source_url`,
`characters`, `offset`, `next_offset`, `page_number`, `page_count`, `content_status`,
`preview`, `limitations` and `artifact_path` provide structured result data.
`region` is a frozen `CaptureRegion(x, y, width, height)` in **source viewport CSS
pixels**. Use `target_id` and `document_id` to choose the correct Canvas surface
and transform those coordinates into its displayed bounds. `image_url` contains
only the bounded screenshot thumbnail. Native download progress remains keyed by
`download_id`; show percentages only when total bytes are known.

Use the enum tags rather than parsing event-name prefixes. Python dispatch uses
event classes and enums; the iframe receives its tag table from `EventKind` rather
than maintaining a second list of wire names. A JSON schema for a frontend can be
generated with `TypeAdapter(WorkPresentedEvent).json_schema()` from Pydantic.

All new presentation receipts are transient: they stay out of model context, saved
session state and run results. Configured secrets are redacted **before** preview
truncation. Terminal logs omit rich preview text and screenshot data. The local view
keeps a bounded, typed receipt cache to restore active work and still-fresh results
after navigation, tab switches or a dialog; a Canvas viewer can retain that state
while its remote document changes. An open native dialog cannot render an iframe,
so its live presentation event lets the surrounding client display it immediately.
