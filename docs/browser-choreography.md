# Browser choreography and video

[Back to README](../README.md) · [Input contracts](browser-interaction.md#input-choreography)

`InputVisualization` renders cursor, keyboard, targets and action feedback inside
the active Chrome tab. The live viewer and native recording see the same page
presentation; native browser toolbars are outside the capture.

![Presentation states](media/choreography/overview.png)

[Play the Chrome recording](media/choreography/demo.mp4). These captures come from
the local walkthrough with real browser input and a scripted thinking receipt;
it makes no model calls.

## Configure or reproduce

```python
from browserrig import IframeRenderer, InputVisualization

presentation = InputVisualization(renderer=IframeRenderer(
    name="Research",
    keyboard_layout="de",
    theme="dark",
))
```

Mount `presentation` in `Agent(plugins=[...])`. Layouts are `en`/`de`, themes are
`dark`/`light`/`auto`. `InputVisualization(renderer=None)` keeps events for an
external viewer. Input pacing is controlled separately by `InputPacing`.

```powershell
uv run python -m examples.visualization --headed --layout de --theme dark
```

Requires FFmpeg and Chrome supporting native Page recording. Omit `--headed` for
headless mode. `--directory` selects output for PNGs, gallery, manifest, timeline
and recordings. Ordinary model screenshots omit viewer surfaces; see
[overlay behavior](browser-composition.md#browser-owned-presentation).

## Session videos

Add `VideoRecording()` to the agent's plugins:

```python
from pathlib import Path
from browserrig import VideoRecording

recording = VideoRecording(Path(".browserrig/recordings"), padding=0.15)
```

Recording starts with the session and creates a unique output directory on close.
It follows tab changes made through Browserrig. Select and close tabs through
`browser.tabs` so captures can be saved; manual Chrome tab selection is not tracked.
FFmpeg must be on `PATH`, and Chrome must support `Page.startScreenRecording`.

| Output | Contents |
| --- | --- |
| `video.mp4` | Edited session: model waits, compaction and pauses cut using `Activity` intervals |
| `original.mp4` | Joined captures retaining those waits |
| Native captures and `timeline.json` | Original segments and timing data |

Tool execution, readiness and human handoff stay visible. Recording splits around
clean screenshots and tab/wait boundaries. Hold the mounted
`session.scope[VideoRecording]` to inspect `.result` after exit, or call
`await session.scope[VideoRecording].finish()` to finish earlier. The OpenAI
example supports `--video .browserrig/recordings`.

## External viewers

Start a consumer before the run and use `session.subscribe(transient=True)` for
input, work, activity and download events. `WorkPresentedEvent` supplies the same
structured receipts to the iframe and external viewers; upsert by `work_id`.
`call_id`/`action_id` correlate execution, and `WorkPhase` identifies running,
completed, warning, failed or cancelled work. Terminal work expires after
`retention` seconds.

Titles/details are ready to draw. Structured fields retain paths, URLs, page
selectors, preview/limitations and source geometry. `CaptureRegion` uses source
viewport CSS pixels; transform it to the viewer's bounds using tab/document
identity. Download progress is
keyed independently by `download_id`; show percentages only with a known total.

Presentation receipts are transient and excluded from model context and saved
results. Configured secrets are redacted before preview truncation. Render preview
text as data. Use exported event classes/enums; a frontend schema can be generated
with `TypeAdapter(WorkPresentedEvent).json_schema()`.

### DOM scroll receipts

`scroll_page` and `scroll_element` publish `DomScrolledEvent` after the browser
reports actual movement. This closes a gap where successful DOM scrolling had only
a text tool result and was invisible to external choreography consumers.
Mount `InputVisualization(renderer=None)` and subscribe before execution:

```python
from browserrig.choreography import DomScrolledEvent

async def consume(session):
    async for event in session.subscribe(transient=True):
        if isinstance(event, DomScrolledEvent):
            dx = event.after[0] - event.before[0]
            dy = event.after[1] - event.before[1]
            # Use event.action_id to correlate with action lifecycle receipts.
            print(event.target_id, event.frame_id, event.ref, dx, dy)
```

| Event | Data and meaning |
| --- | --- |
| `DomScrolledEvent` (`browser.dom.scrolled`) | `before` and `after`: measured `(scrollLeft, scrollTop)` in the scrolled object's local CSS pixels. Subtract to obtain actual deltas, including clamping at boundaries. |
| `ScrollStartedEvent` (`browser.scroll.started`) | `x`, `y`: wheel position in tab viewport CSS pixels; `delta_x`, `delta_y`, `duration`: planned native wheel gesture. |
| `ScrolledEvent` (`browser.scrolled`) | Same wheel position, dispatched deltas and gesture duration after dispatch completes. These are input deltas, not measured DOM offsets. |
| `ActionStartedEvent`, `ActionFinishedEvent`, `ActionFailedEvent` | Durable execution lifecycle, correlated by `action_id`. A finished action can have unchanged scroll offsets. |
| `WorkPresentedEvent` (`browser.work.presented`) | Bounded presentation feedback, including tool failures; DOM movement is carried by `DomScrolledEvent`, not by parsing a work preview. |

`DomScrolledEvent` also carries:

| Field | Meaning |
| --- | --- |
| `browser_id`, `target_id`, `document_id` | Source browser, native tab and top-level document. |
| `frame_id`, `frame_document_id` | Frame and frame document containing the scrolled object, including iframe containers. |
| `ref` | Container ref from that observation, or `""` for `scroll_page` on the outer document. Refs are observation-local identifiers. |
| `action_id` | Executing browser action, shared with its action lifecycle events. |
| `at` | Monotonic event timestamp in seconds. |
| `blocked` | At least one requested axis was disabled by overflow policy. The other axis may still have moved. |

No movement receipt is emitted for unchanged offsets, rejected targets, denied or
failed execution. A partially blocked scroll emits its measured movement with
`blocked=True`. DOM scrolling emits no wheel gesture or pointer trajectory.
Receipts are transient, excluded from saved results and model context, and emitted
only with `InputVisualization` mounted. Direct low-level scroll helpers do not
stage choreography; these receipts cover the supplied DOM scroll tools.

These offsets are content scroll positions, not points in the tab viewport. They
must not be projected as cursor coordinates. Source viewport metadata and resize
projection are tracked separately in [#39](https://github.com/mathisarends/browserrig/issues/39).
