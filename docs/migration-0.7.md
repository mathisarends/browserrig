# Migrate from 0.6.x to 0.7.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#unreleased)

Browserrig 0.7.0 pins Harnessed and its provider, MCP and telemetry extras to
0.19.0. Upgrade Browserrig and the extras your application uses together.

## Configure browser observations

Replace `DomPerception`, `TextContext` and `ImageContext` with
`BrowserPerception`. Use `TextObservations(mode="delta")` or
`TextObservations(mode="full")` in place of `DomText` and `DomTextMode`.
Use `DomCapture(page_prose="inline")`, `"sparse"` or `"off"` in place of
`DomCapture(text=PageText...)`. `PageProse` and `TextMode` are literal types.

```python
from browserrig import BrowserPerception, DomCapture, DomRenderer, TextObservations

perception = BrowserPerception(
    text=TextObservations(mode="full"),
    capture=DomCapture(page_prose="sparse"),
    renderer=DomRenderer(),
)
```

`DomCapture()` is the default. Use `DomRenderer()` for DOM text as shown above.
It reads the snapshot without text or landmark settings. For a custom observation
format, supply your own renderer. Custom text renderers implement
`instructions()` without a screenshot argument.

## Configure screenshots

Move `marks`, `cursor`, `skip_unchanged` and image `retention` to `Screenshots`.
Use `Screenshots(trigger=ScreenshotTrigger.EACH_STEP, skip_unchanged=False)`
to deliver a fresh image at each step. Add `ScreenshotTools()` separately to
allow on-demand screenshots.

```python
from browserrig import BrowserPerception, ScreenshotCapture, Screenshots

perception = BrowserPerception(
    text=None,
    capture=ScreenshotCapture(),
    screenshots=Screenshots(),
)
```

Pixel-only capture supplies an initial on-request image on each new document.
It withholds screenshots when `Secrets` has known values. Use `DomCapture()`
when you need screenshot marks. Low-level `capture(..., screenshots=True)`
returns unannotated pixels, with marks and cursor overlays added when perception
projects the model observation.

## Update DOM tools

Replace `await scope[DomElements].resolve(tab, ref)` with
`await scope[ResolveDomElement](tab, ref)`. Import `ResolveDomElement` from
`browserrig` or `browserrig.observation`. Native DOM tools that take refs
require this service. A capture that returns `DomElementHandle` for its refs
declares `supports_dom_refs = True` to enable it.

## Configure page readiness

Rename `Readiness` to `PageReadiness` in plugin lists, service dependencies
and scope lookups. Readiness policies, checks and reports keep their names.
For the previous browser-event behavior, use
`NetworkQuiet(inner=BrowserReady())` as both the `initial` and `ongoing`
policy on `PageReadiness`.

## Update custom input

Use `Effect(expects_new_tab=True)` in place of `Effect(opens_tab=True)`.
This gives the browser time to open a possible new tab.

Implement `wheel_steps(delta_x=..., delta_y=...)` on custom motors. Return
`WheelStep` values from `browserrig.input` with native CSS-pixel deltas
and `delay_before_seconds`. The deltas must add up to the requested
distance. Inherit from `Instant` or `HumanMotor` to reuse a built-in plan.

## Update eval timeouts

Use `timeout_seconds=` in Python eval APIs and subprocess helpers. Rename
`timeout` to `timeout_seconds` in saved result JSON before comparing runs.
The eval CLI still accepts `--timeout` in seconds.
