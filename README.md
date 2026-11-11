# Browserrig

A composable agent runtime for browser agents, built on
[Harnessed](https://github.com/mathisarends/harnessed). Compose the model, browser,
perception, tools and context policies for your agent. Use the default recipe to
start, replace individual capabilities, or assemble your own runtime from plugins.

## Compose the layers

| Layer | Responsibility | Extension points |
| --- | --- | --- |
| Agent runtime | Model calls, sessions, approvals and persistence | Harnessed models, plugins and lifecycle hooks |
| Browser | Tabs, frames and browser lifetime | `Browser`, `InputTargets`; local or remote `Chrome` |
| Input | Mouse and keyboard, independent of the browser backend | `InputRuntime`, `Input`, `Targeting` |
| Perception | Capture page state and render observations | `DomPerception` or custom `CaptureStrategy`, `References`, `Renderer` |
| Actions | Coordinate input, readiness and action chains | Tool groups, `browser_tool`, `ReadinessPolicy` |
| Context | Select images, compact history and recover task memory | `TextContext`, `ImageContext`, `TaskMemory` |
| Presentation | Pace input, show activity and record sessions | `InputPacing`, `InputVisualization`, `VideoRecording` |

These layers have separate contracts: changing capture does not require changing
the model loop; a workspace can run without a browser; input pacing and
visualization can be configured independently. Chrome/CDP and DOM capture are the
built-in adapters. Custom capture backends can supply their own references and
live target resolution for the shared pointer tools.

## Quick start

Requires Python 3.12+ and Chrome or Chromium:

```sh
python -m pip install "browserrig[openai]"
```

Set `OPENAI_API_KEY`, then run:

```python
import asyncio

from harnessed import PolicyDecision
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import (
    Agent, Chrome, DomPerception, InputPacing, InputVisualization,
    Screenshots, ScreenshotTrigger,
)


async def main():
    agent = Agent(
        model=PydanticAIModel(OpenAIResponsesModel("gpt-6.1-terra")),
        browser=Chrome.launch(url="https://example.com", headless=False),
        plugins=[
            DomPerception(
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing, InputVisualization),
    )
    async with agent.session() as session:
        result = await session.run("Describe this page and cite its URL.", max_steps=10)
        print(result.text)


asyncio.run(main())
```

A plugin in `plugins` replaces the default in the same slot or adds a capability;
`without` removes defaults. The example enables screenshots and automatic tool
approval, and removes input pacing and visualization. By default, side effects
require approval: use `Approvals(approver=...)` to ask through your application.
Chrome opens with the session and closes with it. Use
`Chrome.connect(endpoint="http://localhost:9222")` for an existing CDP browser.

Already using Harnessed? Mount `browser_pack()` in its `Agent`, or select the
individual plugins. `browserrig.Agent` is the ready-made composition of that runtime.

## Co-locate a capability

A plugin keeps its tools, instructions, hooks and session state together. Declare
shared services with `needs(T)` or optional services with `observes(T)`; use
`PluginState` for state belonging to each activation. Resources and registrations
follow the plugin's lifetime.

| Hook | Use |
| --- | --- |
| `PreStep` / `PrepareRequest` | Observe before a step; add current application facts to the model request |
| `ProjectObservation` / `ChangeTab` | Compose observation content or wrap a backend tab operation |
| `SelectReadiness` / `CheckReadiness` | Select a page readiness policy or extend its checks |
| `BrowserToolCall` / `Perform` / `TargetLocated` | Wrap browser execution, stage an intent or react to a resolved target |
| `ObservationsIncludedEvent` | Track the observations actually sent after request processing and compaction |

Context flows through the session scope into tools and hooks. `Actions` binds the
addressed tab; `Runtime` provides a shared `ActionContext` whose ID follows input
and browser operations. Typed events carry that identity to viewers and traces.
`instructions()` supplies fixed guidance,
`PrepareRequest` adds request-only context, and
`session.append_message(UserMessage(...))` adds durable conversation input.
See [composition](docs/browser-composition.md) for a complete co-located plugin,
custom tools and context propagation.

## Documentation

| Guide | Start here for… |
| --- | --- |
| [Composition](docs/browser-composition.md) | Layers, plugins, hooks and custom capture backends |
| [Agent guide](docs/agent-guide.md) | Sessions, streaming, prompts, completion and persistence |
| [Browser interaction](docs/browser-interaction.md) | Direct browser access, refs, coordinates and input |
| [Files and events](docs/files-and-events.md) | Workspaces, remote file bridges, downloads and streams |
| [Choreography and video](docs/browser-choreography.md) | Viewer configuration, captures and recording |
| [Task memory](docs/task-memory.md) · [Todos](docs/todos.md) · [Human handoff](docs/human-handoff.md) | Optional task and human workflows |
| [Telemetry](docs/telemetry.md) · [Development](docs/development.md) | Traces, local setup, checks and releases |

Install `browserrig[files]` for document readers, `browserrig[ocr]` for readers plus
local OCR, or `browserrig[otel]` for tracing. Other extras include `openai`,
`anthropic` and `mcp`. Runnable examples live in [`examples/`](examples).

Early 0.x: APIs may change between minor versions. CI covers Python 3.12–3.14 on
Windows and Linux; macOS is not covered. See the [changelog](CHANGELOG.md) for
compatibility and upgrade notes. [MIT license](LICENSE).
