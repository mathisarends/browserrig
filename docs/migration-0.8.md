# Migrate from 0.7.x to 0.8.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#080-2026-11-18)

Browserrig 0.8 removes the browser defaults helpers and splits pointer tools
by how they address a target. Update custom Harnessed compositions, pointer
tool calls and any event handlers that match reference-based hover actions.

## Use the standard browser agent

If your Harnessed agent used the standard setup, switch to `browserrig.Agent`.
Move the configured Chrome plugin to `browser=` and keep additional plugins in
`plugins=`.

```python
from browserrig import ActionLabels, Agent, Chrome

agent = Agent(
    model=model,
    browser=Chrome.launch(url="https://example.com"),
    plugins=[ActionLabels()],
    instructions=None,
)
```

Pass your existing `instructions=` value. Use `instructions=None` if you
previously relied on Harnessed's empty caller instructions. The standard agent
uses Markdown plugin guidance. Pass your previous `prompt=` if you set one
explicitly or use `SystemPrompt.from_plugins(format=...)` to choose the format.

## Keep a custom Harnessed composition

Remove the helper import and list each plugin in `harnessed.Agent(plugins=[...])`.
Use `agent.describe()` under 0.7.x to inventory the resolved composition.
Translate replacements into the configured plugin you want and leave excluded
plugins out of the list. Keep any application-specific plugins and the prompt
configuration in the composition root as well.

- Start with `Runtime()` and the configured `Chrome` provider. Add
  `InputRuntime()` and `PageReadiness()` for browser observations and input.
- Select a tab policy and configure `BrowserPerception` for the observations
  your model needs. Add `Actions()` for browser tools and list each model-facing
  tool group explicitly.
- List optional capabilities such as `InputPacing()`, `Choreography()`,
  `ChoreographyOverlay()`, [workspace and download plugins](files-and-events.md)
  and `TaskMemory()` where used.

The [screenshot-driven single-tab example](browser-composition.md#compose-a-screenshot-driven-single-tab-agent)
shows the infrastructure, observation, tab policy and input tools in one list.

## Select pointer tools

| In 0.7.x | In 0.8.0 |
| --- | --- |
| `PointerTools.move_mouse(x, y)`, `click_at`, `drag_at` | Keep `PointerTools()`. Supply both coordinates to `move_mouse(x, y)`. |
| `PointerTools.click(ref)`, `drag(source_ref, target_ref)` | Use the same tool names with `ReferencePointerTools()`. |
| `PointerTools.move_mouse(ref=...)` | Call `hover(ref=...)` on `ReferencePointerTools()`. |

In an explicit composition, add `Targeting()` for `ReferencePointerTools()` and
configure perception to resolve element refs. If your agent only uses screenshot
or viewport coordinates, select `PointerTools()`.

The standard `browserrig.Agent` includes both plugins. If you previously passed
`without=(PointerTools,)` to remove every pointer tool, use
`without=(PointerTools, ReferencePointerTools)`. For screenshot-only perception
in the standard agent, exclude `ReferencePointerTools`.

Update event handlers or telemetry filters that treated reference-based hover
as `ActionKind.MOVE_MOUSE` (`"move_mouse"`). Those actions now use
`ActionKind.HOVER` (`"hover"`). Coordinate moves still use
`ActionKind.MOVE_MOUSE`.

See [pointer tool composition](browser-composition.md#choose-pointer-tools).
