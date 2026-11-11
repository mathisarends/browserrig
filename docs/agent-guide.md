# Agent guide

[Back to README](../README.md) · [Composition and hooks](browser-composition.md)

`browserrig.Agent` composes Harnessed's native runtime with the browser pack.
`run()`, `session()`, streaming, controls and persistence remain Harnessed APIs.
See the [quick start](../README.md#quick-start) for a complete runnable example.

## Configure an agent

Pass a model or a `PydanticAIModel(...)` wrapper, a configured `Chrome` plugin,
`instructions=` for caller guidance, and `plugins=` for capabilities. Constructors
validate configuration; resources open with the session.

```python
from browserrig import Agent, Chrome, Done, TerminalEvents

agent = Agent(
    model=model,
    browser=Chrome.launch(url="https://example.com", headless=False),
    instructions="Research the task and include source URLs.",
    plugins=[Done(), TerminalEvents()],
)
result = await agent.run("Describe this site.", max_steps=20)
print(result.text)
```

`model` is supplied by your application. Configure `Approvals(approver=...)` from
`harnessed.plugins` to ask through your UI, or explicitly allow actions with
`Approvals(default=PolicyDecision.ALLOW)` from `harnessed`. Side effects are
rejected without an approval handler or an allow policy.

## Composing plugins

A supplied plugin replaces the default in the same slot; other plugins are added.
`without=(PluginType, ...)` removes defaults, and `None` entries are skipped.
Conflicting explicit plugins raise `PluginConflict`. Use `browser_pack()` in an
existing Harnessed agent, or mount individual capabilities. The
[composition guide](browser-composition.md) covers recipes, dependency injection,
co-located features and extension hooks.

`agent.describe()` reports the resolved plugins and replacements. Startup validates
required services and raises `PluginDependencyError` for missing dependencies.
Use `plugin_validation=PluginValidation.WARN` only when services will deliberately
be mounted later; both types come from Harnessed (`PluginDependencyError` from
`harnessed.errors`).

## Sessions, streaming and context

A session keeps the browser and conversation open across turns:

```python
from harnessed.events import TextDeltaEvent
from harnessed.models import UserMessage

async with agent.session() as session:
    await session.append_message(UserMessage("Include exact source URLs."))
    async with session.stream("Compare the two missions.", max_steps=20) as run:
        async for event in run:
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="", flush=True)
        result = await run.result()
    follow_up = await session.run("Which launched first?")
```

`append_message` adds durable background without invoking the model. Await it
before starting work that depends on it; an in-flight request is unchanged.
Messages follow ordinary retention and compaction. For changing application facts,
use a [`PrepareRequest` hook](browser-composition.md#co-locate-tools-instructions-hooks-and-state)
to add request-only messages.

The default [task memory](task-memory.md) compacts at 80% of the model window,
falling back to 100,000 tokens when the window is unknown. `ImageContext()` keeps
the latest screenshot. Override these policies independently in `plugins`.

## Session controls

```python
handle = await session.submit("Inspect this page.")
await session.pause()
await session.inbox.steer("Focus on the navigation.")
await session.resume()
result = await handle.result()
```

Use this inside an open session. Pause waits for a complete step boundary and
leaves Chrome running; resume obtains a fresh observation. `session.stop()` ends
work gracefully, while `session.abort()` interrupts it immediately.
[HumanHandoff](human-handoff.md) adds model-requested takeover and receipts for
external browser changes.

## Action chains and stable tool kinds

Known independent form fields can be filled in one model response, with submission
last. Inputs execute sequentially. New suggestions, validation failures, modals,
navigation or changed tabs interrupt the remaining calls so the model can observe
again. A successful input remains successful if its comparison probe fails.

Navigation, tab changes, scrolling, drags, coordinates, JavaScript, uploads,
dialogs, waiting and screenshot requests end the chain. Later unstarted calls are
`SKIPPED`. Tool acknowledgements describe attempted input; the next observation
is where the agent verifies the intended result. Browser inputs are not replayed
by observation recovery.

Tools declare `ActionKind` through `BrowserToolMetadata`; custom policy and
execution hooks can inspect `event.tool.metadata.get(BrowserToolMetadata)`.
Import `ActionKind` from `browserrig` and `BrowserToolMetadata` from
`browserrig.tools`. See
[custom browser tools](browser-composition.md#add-a-browser-tool).

## Explicit completion and output formats

Without `Done()`, a text response without tool calls completes the turn. With
`Done()`, standalone text is progress: the model must call `done(success=...)`
alone, then provide its final answer. Application tools are denied after accepted
completion. The success flag is the agent's report; `result.completed` means the
turn ended normally.

Use native `output=` for a validated result:

```python
from pydantic import BaseModel


class Comparison(BaseModel):
    conclusion: str
    sources: list[str]


result = await agent.run("Compare the missions.", output=Comparison, max_steps=20)
if result.completed:
    print(result.output)
```

With `Done`, structured output constraints apply after the completion receipt;
progress remains unconstrained. Native validation and retries apply. Read
`result.output` for the typed answer; `result.text` may be empty in tool-output mode.

## Step limits and optional final summaries

`max_steps=` bounds the whole turn, including completion and validation retries.
For a reserved final text summary, configure
`AgentLoop(max_steps=20, final_step=FinalStepPolicy.SUMMARIZE)` from
`harnessed.plugins`. The summary consumes the last step and returns
`completed=False`; it does not extend the budget.

## System prompts and optional MCP tools

The browser pack collects each selected plugin's `instructions()` in configured
list order. `instructions=` prepends caller guidance. Use
`prompt=SystemPrompt.from_plugins(format=PromptFormat.XML)` to change formatting;
a standalone `SystemPrompt(...)` document omits plugin blocks. These types come
from `harnessed`. Inspect `agent.prompt` or `await session.prompt.render()`.

A runtime mount uses `async with session.use(plugin,
section_delivery=SectionDelivery.CONTEXT): ...` to deliver its guidance until it
closes; `SectionDelivery.IGNORE` skips it. The fixed system prompt stays unchanged.

Install `browserrig[mcp]` and add
`MCP.http("catalog", url=endpoint, include_tools=["search"])` from
`harnessed.plugins.mcp` for external tools. `MCP.stdio(...)` starts a local server.
Connections belong to each session, tools are namespaced, and approval policies
apply. Failed operations are not automatically retried.

## Navigation and secrets

Follow observed links with `click(ref=...)`; `new_tab=True` keeps the current page
open. `search(query=...)` starts a DuckDuckGo search, while `navigate(url=...)`
opens a known destination. On a search page, use its observed search controls.

`AllowedDomains(["example.com", "*.example.com"])` optionally restricts document
navigation, including redirects, popups and frames. Wildcards exclude the apex;
add it explicitly. Empty lists deny all sites. Subresource traffic is unaffected,
and arbitrary JavaScript tools are disabled while the guard is mounted. This is a
navigation policy, not a network or execution sandbox.

`Secrets({name: Secret(value=..., domains=[...])})` exposes placeholders such as
`{{secret:NAME}}` for `type_text` and `send_keys`. Values are resolved for typing on
allowed origins and redacted from Browserrig observations and receipts. JavaScript
tools are unavailable while secrets are configured. Telemetry has its own explicit
[content redaction policy](telemetry.md#use-in-an-application).

## Saving and restoring sessions

```python
from pathlib import Path
from harnessed.integrations.json import JsonSessionStore
from browserrig import Agent, Files, LocalWorkspace

agent = Agent(
    model=model,
    store=JsonSessionStore(root=Path(".browserrig/sessions")),
    plugins=[Files(LocalWorkspace(".browserrig/research"))],
)
async with agent.session(id="research") as session:
    await session.run("Find the launch dates.")

async with agent.session(id="research") as session:
    result = await session.run("Compare their trajectories.")
```

Storage is opt-in. Awaited runs commit terminal state; `session.flush()` commits
pending state. Reopening restores conversation/checkpoint data and retained image
assets, while browser connections, tabs and DOM refs start fresh. Workspace files
are separate: reuse the same directory to retain them. Paused sessions remain
paused; supply `restore_outputs=[YourOutputType]` before resuming structured work.

For explicit continuation without a store, serialize `result.state.to_json()` and
pass `state=SessionState.from_json(saved)` to `run()` or `session()`.
Harnessed 0.16 uses state/checkpoint format 3 and audit envelope 6; older formats
require separate stores. See the [upgrade notes](../CHANGELOG.md) and
[session-store example](../examples/session_store.py).
