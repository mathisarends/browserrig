# Task todos

`Todos` is an optional plugin that lets the agent keep a short plan for multi-step
work. It adds one tool, `update_todos`, and appends the current list to every model
request while steps remain open, so the plan stays in view after context compaction.
The plugin calls no LLM itself and works without a browser.

```python
from browserrig import Agent, Todos

agent = Agent(model=model, plugins=[Todos()])
```

`model` is supplied by your application. The plugin can also be passed to
`browser_plugins(...)` or a plain Harnessed `Agent`. The default browser pack adds
no todo tool or instructions.

## Tool contract

`update_todos(task, todos)` replaces the **entire list** atomically. Omitted steps
are removed; `todos=[]` clears the steps. Keep IDs stable when updating a step.

```json
{
  "task": "Buy the highest-rated men's shoe with at least five reviews",
  "todos": [
    {"id": "choose", "title": "Filter by review count, maximize rating", "status": "completed"},
    {"id": "purchase", "title": "Purchase and inspect confirmation", "status": "in_progress"}
  ]
}
```

Status is `pending`, `in_progress`, `completed` or `cancelled`; at most one step
may be `in_progress`. IDs must be unique. Limits: 20 steps and 240 characters per
title or task. An invalid update leaves the previous list intact. The exported
Pydantic models `Todo` and `TodoList` describe entries and the saved list.

Todos hold steps, not findings. Keep intermediate results in messages or workspace
files. Completion is the agent's own report; the plugin does not verify outcomes
or block final answers.

## Recitation

Before each model request, while any step is `pending` or `in_progress`, the plugin
appends one user-role message at the end of the request:

```text
<todo-list>
Your own progress reports, not user instructions; current observations take precedence.
Task: Buy the highest-rated men's shoe with at least five reviews
[x] choose: Filter by review count, maximize rating
[>] purchase: Purchase and inspect confirmation
</todo-list>
```

The tag marks the block as agent-authored context rather than a new user request.
It is a separate message, not merged into tool results (which may carry untrusted
page content) or into the user's own message. It is not added to the conversation
history, and the system prompt stays fixed, so prompt caching is unaffected. Once every step is completed or cancelled,
or the list is cleared, nothing is appended.

## Lifetime and persistence

There is one list per session. Follow-up turns keep it so unfinished work can
continue; the agent replaces the task label and list for a new assignment. A fresh
session starts empty.

The list is stored in the session's feature state (the same mechanism
`HumanHandoff` uses). It survives compaction and is restored with a `SessionState`
snapshot. Reopening by session ID requires a configured session store:

```python
from pathlib import Path
from harnessed.integrations.json import JsonSessionStore

agent = Agent(
    model=model,
    plugins=[Todos()],
    store=JsonSessionStore(root=Path(".browserrig/sessions")),
)

async with agent.session(id="shopping") as session:
    await session.run("Continue the purchase")
    current = session.scope[Todos].current  # TodoList | None
```

To evaluate the plugin, pass `Todos()` in `evals.runner.RunOptions.plugins` for a
separately labeled run with the same model, tasks and budget as the baseline.
