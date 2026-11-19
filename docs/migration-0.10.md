# Migrate from 0.9.x to 0.10.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#unreleased)

## Compose perception from plugins

`BrowserPerception` keeps the observation lifecycle: readiness, capture,
redaction, delivery and image history. What an observation contains comes from
plugins mounted beside it. `browserrig.Agent` includes `BrowserPerception()`,
`Screenshots()`, `DomPage()` and `SetOfMarks()`; pass a plugin to replace its
default or remove it with `without=`.

```python
# 0.9
BrowserPerception(
    text=TextObservations(mode="full"),
    capture=DomCapture(page_prose="sparse"),
    screenshots=Screenshots(
        trigger=ScreenshotTrigger.EACH_STEP,
        marks=SetOfMarks(),
        cursor=True,
    ),
)
```

```python
from browserrig import (
    BrowserPerception,
    CursorMarker,
    DomPage,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
)

plugins = [
    BrowserPerception(text="full"),
    DomPage(prose="sparse"),
    Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
    SetOfMarks(),
    CursorMarker(),
]
```

| 0.9 | 0.10 |
| --- | --- |
| `TextObservations(mode="delta")` / `mode="full"` | `BrowserPerception(text="delta")` / `"full"` |
| `TextObservations(content="metadata")` | Omit `DomPage`; without a page model, observations carry the metadata header |
| `DomCapture(page_prose=...)` | `DomPage(prose=...)` |
| `ScreenshotCapture()` | No page model: `BrowserPerception(text=None)` with `Screenshots` |
| `Screenshots(marks=SetOfMarks())` | `SetOfMarks()` plugin |
| `Screenshots(cursor=True)` | `CursorMarker()` plugin |
| `BrowserPerception(screenshots=Screenshots(...))` | `Screenshots(...)` plugin |

In the standard agent, change only what differs:

```python
from browserrig import Agent, DomPage, Screenshots, ScreenshotTrigger, SetOfMarks

agent = Agent(
    model=model,
    plugins=[Screenshots(trigger=ScreenshotTrigger.EACH_STEP)],
    without=(DomPage, SetOfMarks),
)
```

## Port custom capture strategies

Implement `PageModel` instead of `CaptureStrategy` and `Renderer`. `collect`
receives a `CaptureRequest` with the readiness report, screenshot flag, region,
zoom and cursor, and returns `PageCapture(page, references)`. `render(snapshot)`
formats the observation text. Register the model from a plugin during setup; the
plugin contributes its own instructions.

```python
from harnessed import Plugin
from harnessed.kernel import PluginScope, needs

from browserrig import BrowserPerception


class CanvasPage(Plugin):
    _perception = needs(BrowserPerception)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.use_model(CanvasModel()))
        scope.effect(self._perception.use_frames(CanvasFrames()))
```

`PageContent` lists `targets` and model-specific `parts` instead of DOM fields.
Subclass `Target` for model data and `PagePart` for page-level data; set `text`
to the raw page text so secret checks can withhold an image. `FrameSource`
supplies images when the viewport is not the right source, and
`ImageAnnotator` draws custom overlays. `supports_dom_refs` is gone: DOM tools
use `ResolveDomElement`, which `DomPage` provides.

## Read targets instead of elements

| 0.9 | 0.10 |
| --- | --- |
| `snapshot.elements` | `snapshot.targets` |
| `snapshot.element(ref)` | `snapshot.target(ref)` |
| `snapshot.headings`, `content`, `offscreen`, `modal`, `alerts`, `cookie_banners`, `canvases` | `DomView.of(snapshot).headings`, ... |
| `BrowserPerception.element(tab, ref)` | `BrowserPerception.target(tab, ref)` |
| `ElementHandle.element` | `TargetHandle.target` |
| `CaptureContent` | `PageCapture` |

DOM targets remain `ElementInfo` instances; `DomView.of(snapshot).elements`
returns them typed. `DomElementHandle.element` is unchanged.

## Update imports

DOM extraction, rendering, search and handles moved from `browserrig.observation`
to `browserrig.dom`, for example `DomReferences`, `ElementInfo`, `render`,
`search_content` and `extract_document`. Imports from the top-level `browserrig`
facade are unchanged for names that still exist.

## Snapshot serialization and fingerprints

`Snapshot.model_dump` and `model_dump_json` keep target and part fields, but
`Snapshot.model_validate_json` cannot restore DOM targets and parts. Keep your
own typed records if you persist snapshots for later validation. Page
fingerprints also cover the raw page text, so a stored 0.9 fingerprint does not
match a 0.10 fingerprint of the same page.
