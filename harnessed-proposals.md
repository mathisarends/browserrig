# Harnessed API proposals from browserrig

Three places where browserrig works around a missing Harnessed extension point. All
workarounds behave correctly today, but they depend on Harnessed internals or bypass
the declarative plugin API. Found while reviewing browserrig against **Harnessed 0.13.0**,
2026-11-07. No upstream issue has been filed yet.

## 1. A hook for the structured-output phase

### Problem

`browserrig.completion.Done` needs to change how a run's final answer is produced:

- Before `done()` is called, ordinary text is progress commentary. The output schema
  must not be enforced, but the model should still see it as an instruction.
- After `done()`, the next request must carry no tools, an extra system instruction
  and the run's native output contract. Only that response is validated.

Harnessed has no public hook for either step:

- `PrepareRequest` is dispatched in `Stepper` **before** `OutputHandler.prepare`, so a
  plugin cannot see or undo what `prepare` adds (`output_schema`, the reserved
  `final_answer` tool).
- `OutputHandler.validate` is called directly, with no hook around it.

### Current workaround (`browserrig/completion.py`)

`Done.setup` replaces `OutputHandler.prepare` and `OutputHandler.validate` **on the class,
for the whole process**. A module-level dict `_COMPLETIONS: dict[SessionLog, Done]`
routes each call to the right session through the handler's internal `self.log`
attribute. `restore()` puts the native methods back once no session uses them.

Risks:

- Any change to `OutputHandler`'s signature, its `log` attribute or the order of calls
  in `Stepper` breaks completion silently. No type checker or test in Harnessed catches it.
- Process-global mutable state for a per-session concern. Two libraries using the same
  trick would overwrite each other's patch.
- Every hook in `Done` has to check `event.session.log is self._session.log`.

### Proposal

Two waterfall hooks around the existing handler, dispatched on the session scope, with
the native behavior as the default terminal handler:

```python
class PrepareOutput(Waterfall[ModelRequest]):
    """Shape a request's output contract; the default applies native/tool output."""
    request: ModelRequest
    schema: OutputSchema | None
    model: Model

class ValidateOutput(Waterfall[tuple[dict[str, ToolResult], str | None]]):
    """Validate a response against the output contract; the default is native validation."""
    response: AssistantMessage
    schema: OutputSchema | None
```

`Stepper` would call `scope.dispatch(PrepareOutput(...), default=outputs.prepare)` and
`scope.dispatch(ValidateOutput(...), default=outputs.validate)`.

`Done` then becomes two ordinary hooks, and the global patch, `_COMPLETIONS`,
`_NATIVE_PREPARE` / `_NATIVE_VALIDATE` and the `restore()` bookkeeping go away:

```python
@hook(PrepareOutput)
async def _prepare(self, event: PrepareOutput, next_: Next[ModelRequest]) -> ModelRequest:
    if self._finished():
        request = replace(event.request, tools=(),
                          messages=(*event.request.messages, SystemMessage(_FINAL_INSTRUCTION)))
        return await next_(replace(event, request=request))
    ...  # schema as instruction, output_schema=None, no next_()

@hook(ValidateOutput)
async def _validate(self, event: ValidateOutput, next_):
    return await next_() if self._finished() else ({}, None)
```

Harnessed's own "final step" logic in `Stepper` (strip tools, append
`_FINAL_STEP_INSTRUCTION`) is the same shape. It could become the first built-in user of
`PrepareOutput`.

## 2. Tool options that depend on plugin configuration

### Problem

`@tool(...)` options are evaluated when the class is defined, so they cannot depend on
constructor arguments. `browserrig.handoff.HumanHandoff` needs the tool timeout to be
`self.timeout + 60`, because the tool waits for a human for up to `self.timeout` seconds.
The default 30 s tool timeout would cancel every handoff.

### Current workaround (`browserrig/handoff/plugin.py`, `setup`)

`HumanHandoff` declares `request_human` as a plain method and registers it by hand:

```python
_tools = needs(ToolRegistry)

async def setup(self, ctx: Scope) -> None:
    self._tools.register(
        self.request_human,
        owner=ctx,
        description="...",
        timeout=self.timeout + 60,
        readonly=True,
        chain=ToolChain.STOP_AFTER,
    )
```

Costs:

- The only tool in browserrig that is not declared with `@tool`. Readers looking for the
  plugin's tools on the class do not find it.
- An extra dependency on `ToolRegistry` and on the exact `register` signature, plus
  manual ownership (`owner=ctx`) that the decorator otherwise handles.
- Description and options live in `setup` instead of next to the method.

### Proposal

Let `@tool` options accept a callable that receives the mounted plugin and is resolved
at activation, in the same place where `_activation_tool` already binds the instance:

```python
@tool(
    description="Hand browser control to a human ...",
    timeout=lambda self: self.timeout + 60,
    readonly=True,
    chain=ToolChain.STOP_AFTER,
)
async def request_human(self, reason: str, ...) -> str: ...
```

Starting with `timeout` is enough for browserrig. `enabled` already accepts a callable
(`ToolEnabled`), so a resolver for other options would follow an existing pattern.

A smaller alternative: a `configure_tools(self) -> Mapping[str, ToolOverrides]` method
on `PluginBase` that Harnessed applies at activation. It keeps the decorator unchanged
but splits a tool's options across two places, so the callable form is preferable.

## 3. Tracing hook handlers and library methods

### Problem

`OpenTelemetryTracer` exports `turn`, `step`, `model` and `tool` spans. Everything
between them is one opaque block:

- **Hook handlers have no spans.** `EventBus.dispatch` (`harnessed/kernel/events.py`,
  `invoke`) calls each listener directly. A slow `PreStep` handler, such as
  `BrowserPerception._before_step` capturing the page, shows up only as step time that is
  not model time. Nothing says which plugin's handler it was.
- **Libraries cannot add spans without internals.** `Tracer`, `Span` and `span()` live in
  `harnessed.core.tracing` and are not exported from a public module.
- **Library code has no tracer in reach.** `span()` needs the `Scope`, but most of the
  measured work is in free functions and services several calls below a plugin
  (page extraction, readiness polling, frame discovery).
- **Every name and attribute gets a `harnessed.` prefix.** Spans come out as
  `harnessed.Actions.run`, and source locations as `harnessed.code.filepath`, so tools
  that understand OpenTelemetry's `code.*` conventions cannot link a span to its source.

### Current workaround (`browserrig/core/tracing.py`)

`Chrome` hooks `ExecuteTool` and `PreStep` with `priority=-1000`, injects
`Tracer | None` and binds it in a `ContextVar` around `next_()`. `@traced` methods read
that variable and open `tracer.span(fn.__qualname__, **{"code.filepath": ...,
"code.lineno": ...})`. Spans nest correctly because `OpenTelemetryTracer` uses
`start_as_current_span`, and asyncio tasks copy the context.

Costs: it imports `harnessed.core.tracing`, depends on hook priorities to be outermost,
and misses browser work done outside a tool call or `PreStep`, for example in a
`TurnStopping` handler.

### Proposal

1. **A span per hook handler**, opt-in, around `invoke` in `EventBus.dispatch`:

   ```python
   with span(scope, "hook", event=type(event).__name__, plugin=owner_name,
             **code_location(listener.callback)):
       return await resolve(listener.callback(*bound.args, **bound.kwargs))
   ```

   For a `Waterfall`, `next_()` runs inside the handler's span, so the rest of the chain
   nests below it and each handler's own time is its span minus its children. `Emit`
   events fire often, so this should be off by default:
   `OpenTelemetryTracer(trace_hooks=True)`, or a minimum duration below which hook spans
   are dropped.
2. **A public tracing module**, e.g. `harnessed.tracing`, exporting `Tracer`, `Span` and
   `span`.
3. **An ambient tracer.** The runtime binds the session's tracer in a `ContextVar`
   for the turn, and `harnessed.tracing.current()` (or `span(name)` without a scope)
   reads it. browserrig's `ExecuteTool`/`PreStep` binding hooks would go away.
4. **Instrumentation names and source locations.** Leave names that already carry a
   namespace (`browserrig.Actions.run`) unprefixed, and export
   `code.function.name`, `code.file.path` and `code.line.number` as given.

## Also worth considering: dispatch without keeping the Scope

Three browserrig plugins keep their `Scope` from `setup` only to dispatch hook events
later (`Readiness` → `SelectReadiness` / `CheckReadiness`, `BrowserPerception`,
`Actions`). Each stores `context: Scope | None = None` in plugin state and asserts it is
set before use. A service such as `needs(Dispatcher)`, or `self.dispatch(event)` on a
mounted plugin, would remove that pattern.
