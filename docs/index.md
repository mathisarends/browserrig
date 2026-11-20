# BrowserRig documentation

The [README](../README.md) describes how BrowserRig integrates with Harnessed.
Use the guides below to configure the SDK or find a
[runnable example](examples.md) in the repository.

| I want to… | Read |
| --- | --- |
| Choose plugins, customize observations or write a browser tool | [Composition](browser-composition.md) |
| Run turns, stream responses, configure approvals or reopen sessions | [Agent guide](agent-guide.md) |
| Control Chrome directly or work with references and coordinates | [Browser interaction](browser-interaction.md) |
| Work with downloads, workspace files and event streams | [Files and events](files-and-events.md) |
| Show browser activity live or record it | [Choreography and video](browser-choreography.md) |
| Keep task context and progress across a long run | [Task memory](task-memory.md) and [Todos](todos.md) |
| Give a person control during a session | [Human handoff](human-handoff.md) |
| Trace model requests and browser actions | [Telemetry](telemetry.md) |
| Run project checks or prepare a release | [Development](development.md) |

Install `browserrig[files]` for document readers, `browserrig[ocr]` for readers
with local OCR, or `browserrig[otel]` for tracing. Provider and integration
extras include `openai`, `anthropic` and `mcp`.

For upgrades, see the [migration guides](migrations.md) and the
[changelog](../CHANGELOG.md).
