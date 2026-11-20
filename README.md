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

## Requirements

BrowserRig requires Python 3.12 or newer and access to Chrome or Chromium.
The Python package is `browserrig`. The `openai` and `anthropic` extras add
provider integrations.

## Run a browser agent

`browserrig.Agent` bundles the standard browser plugins. This example opens
a page and asks the agent to summarize it. The model uses the `openai` extra
and reads `OPENAI_API_KEY` from the environment.

```python
import asyncio

from browserrig import Agent, Chrome

model = "openai-responses:gpt-6.1-terra"
url = "https://example.com"
agent = Agent(model=model, browser=Chrome.launch(url=url))


async def main() -> None:
    result = await agent.run("Summarize the page and include its URL.", max_steps=5)
    print(result.text)


asyncio.run(main())
```

`agent.run()` opens a session for one turn. Use `agent.session()` to keep the
browser and conversation open across turns. Use `Chrome.connect(endpoint=...)`
to attach to an existing Chrome instance over CDP. See the
[agent guide](docs/agent-guide.md) for sessions and streaming.

## Compose the runtime

For the same page summary, the agent only needs to observe the page. Replace
the `agent = ...` line above with this explicit composition.

```python
from harnessed import Agent

from browserrig import (
    BrowserPerception,
    Chrome,
    DomPage,
    InputRuntime,
    PageReadiness,
    Runtime,
)

agent = Agent(
    model=model,
    plugins=[
        Runtime(),
        Chrome.launch(url=url),
        InputRuntime(),
        PageReadiness(),
        BrowserPerception(),
        DomPage(),
    ],
)
```

`BrowserPerception` manages observations and `DomPage` supplies page text and
control references. Each additional plugin adds a capability to the runtime.
For example, `Screenshots` adds image capture, and tool plugins give the model
actions it can call. See [composition](docs/browser-composition.md) for the
available plugins and their dependencies.

## Documentation

- [Composition](docs/browser-composition.md) explains the standard runtime,
  plugin selection and extension points.
- [Agent guide](docs/agent-guide.md) covers sessions, streaming and persistence.
- [Browser interaction](docs/browser-interaction.md) covers direct control,
  references and coordinates.
- The [documentation index](docs/index.md) lists the remaining guides.

See the [changelog](CHANGELOG.md) for release history. BrowserRig is early 0.x
software. CI covers Python 3.12–3.14 on Windows and Linux. [MIT license](LICENSE).
