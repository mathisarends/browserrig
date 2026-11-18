# Migrate from 0.7.x to 0.8.0

[Back to README](../README.md) · [Changelog](../CHANGELOG.md#unreleased)

Browserrig 0.8 removes `browser_pack()` and `browser_plugins()`. Both helpers
supplied the standard browser plugin list to custom Harnessed agents. With
explicit composition, adding a tool to the standard agent leaves your custom
agent's tool list unchanged.

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

`PointerTools()` now provides `move_mouse(x, y)`, `click_at` and `drag_at`.
If your custom agent uses element refs, add `Targeting()` and
`ReferencePointerTools()` for `click(ref)`, `drag(source_ref, target_ref)` and
`hover(ref)`. Update any calls to `move_mouse(ref=...)` to use `hover(ref=...)`.
See [pointer tool composition](browser-composition.md#choose-pointer-tools).
