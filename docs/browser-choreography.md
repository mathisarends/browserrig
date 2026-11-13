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
