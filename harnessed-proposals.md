# Harnessed API proposals from browserrig

Two places where browserrig works around a missing Harnessed extension point. Both
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

## Also worth considering: dispatch without keeping the Scope

Three browserrig plugins keep their `Scope` from `setup` only to dispatch hook events
later (`Readiness` → `SelectReadiness` / `CheckReadiness`, `BrowserPerception`,
`Actions`). Each stores `context: Scope | None = None` in plugin state and asserts it is
set before use. A service such as `needs(Dispatcher)`, or `self.dispatch(event)` on a
mounted plugin, would remove that pattern.
