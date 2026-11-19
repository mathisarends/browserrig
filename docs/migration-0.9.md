# Migrate from 0.8.x to 0.9.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#090-2026-11-19)

## Upgrade Harnessed

Upgrade Browserrig along with the provider, MCP and OTel extras your application
uses. Browserrig 0.9 pins Harnessed and those extras to 0.20.0. If your own
extensions import from `harnessed.services` or `harnessed.core`, update them to
the domain modules. For example, import `ToolRegistry` from `harnessed.tools`,
`SessionContext` from `harnessed.sessions` and `Summarizer` from
`harnessed.plugins.compaction`. The upstream release lists the other import
moves and event registry changes. [Harnessed 0.20.0 release notes](https://github.com/mathisarends/harnessed/releases/tag/v0.20.0)

Existing Harnessed state and checkpoints continue to use format 3 and
standalone audit envelopes use format 6.

## Catch Browserrig errors at the browser API boundary

Replace handlers for cdpify's `CDPError` around `Tab` and `Frame` methods,
`browserrig.browser.screenshot()` and observation capture with handlers for
`browserrig.core.BrowserError`. Where you need a CDP error code or message,
inspect `error.__cause__` and check its type. Direct calls through `tab.cdp` or
`frame.cdp` still need cdpify exception handling.

## Refresh stale coordinate sources

`click_at`, `drag_at` and `move_mouse(x, y)` check the latest observation and
the screenshot included in the model request against the current tab, document,
viewport and tracked layout. A retained image can become stale after scrolling
or other input that invalidates its layout. Request a fresh image with
`screenshot` when available, or take the next image in an automatic capture
session. In a text-only session, use the next observation's viewport coordinates.
When a managed action is rejected as stale, inspect the new observation before
retrying.

For custom interfaces, provide `AppState` to track changes Browserrig cannot
derive from Chrome. Return `Generation(state=..., layout=...)` from
`generation(tab)`, changing `state` when observed targets expire and `layout`
when coordinate mappings expire. Return a reason from `blocked(tab)` while
input is unavailable. For code that constructs its own coordinate sources,
carry the snapshot's `generation` forward, for example with
`CapturedImage.from_snapshot(snapshot, browser_id)`. Existing `CheckAction`
hooks can now read `action.observation` and `action.coordinates` after
Browserrig's built-in validation. [Application state and action validation](browser-composition.md#validate-an-action-before-dispatch)

## Select or invoke the wait tool

The standard agent and compositions with `NavigationTools()` still offer
`wait(seconds=...)`. Mount `WaitTools()` to add wait independently or configure
it with `max_seconds` and `description`. The default is one second, capped by
the configured maximum. Code that called the removed `NavigationTools.wait`
method can execute the registered tool through the session registry.

```python
from harnessed import ToolCall
from harnessed.tools import ToolRegistry

result = await session.scope[ToolRegistry].execute(ToolCall("wait", {"seconds": 2}))
```

## Update trace consumers

With content capture enabled, Harnessed model spans expose OpenInference fields.
Update consumers that read the previous JSON attributes.

| Previous model-span attribute | OpenInference attribute prefix |
| --- | --- |
| `input.value` | `llm.input_messages` |
| `output.value` | `llm.output_messages` |
| `request.tools.value` | `llm.tools` |
| `request.settings.value` | `llm.invocation_parameters` |

Model input spans show newly introduced messages by default. Use
`full_input_messages=True` if your consumer needs the full request on each
span. Review custom content filters for the new image stand-ins and
per-message-part content limits. Use the screenshot asset ID to correlate
`browserrig.observation` and `browserrig.operation` spans with the model
request. The eval analyzer supports both trace formats.
[Telemetry attributes and capture options](telemetry.md#screenshot-and-action-attributes)
