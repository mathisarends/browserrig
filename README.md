# BrowserRig

BrowserRig is a composable Python SDK for building browser agents with
[Harnessed](https://github.com/mathisarends/harnessed). It connects an agent
to Chrome and gives it tools to navigate, read pages, click controls and type.

## How it works

Harnessed runs the model loop, manages sessions and applies tool approvals.
BrowserRig turns browser state into observations the model can use. Those
observations can include page text, references to controls and screenshots.
When the model requests a browser action, BrowserRig performs it in the live
browser, resolving control references when needed. The next observation
reflects the resulting page state.

`browserrig.Agent` bundles the standard browser plugins. For a custom
runtime, use `harnessed.Agent` and supply the plugins your application needs.
The browser connection, observations, input tools and viewer are separate
capabilities. You can launch Chrome or connect to an existing instance over
CDP, choose what the model sees, and select the tools it can call.

## Requirements

BrowserRig requires Python 3.12 or newer and access to Chrome or Chromium.
The Python package is `browserrig`. The `openai` and `anthropic` extras add
provider integrations.

## Documentation

- [Composition](docs/browser-composition.md) explains the standard runtime,
  plugin selection and extension points.
- [Agent guide](docs/agent-guide.md) covers sessions, streaming and persistence.
- [Browser interaction](docs/browser-interaction.md) covers direct control,
  references and coordinates.
- The [documentation index](docs/index.md) lists the remaining guides.

See the [changelog](CHANGELOG.md) for release history. BrowserRig is early 0.x
software. CI covers Python 3.12–3.14 on Windows and Linux. [MIT license](LICENSE).
