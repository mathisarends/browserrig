# Task todos

`Todos` is an optional plugin that lets the agent keep a short plan for multi-step
work. `update_todos` saves the plan; `read_todos` recalls it on demand. Both return
the saved list. Reminders contain a short tool reference, not the plan's contents.
The plugin calls no LLM itself and works without a browser.

```python
from browserrig import Agent, Todos

agent = Agent(model=model, plugins=[Todos()])
```

`model` is supplied by your application. The plugin can also be passed to
`browser_plugins(...)` or a plain Harnessed `Agent`. The default browser pack adds
no todo tool or instructions.

## Tool contract

`read_todos()` returns the current task and every step, including completed and
cancelled steps. Before the first update it returns `No todo list saved.` Reading
refreshes the reminder just like a successful update, without changing the plan.

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

The tool result is the saved list, so it stays in the conversation like any other
tool result:

```text
Saved todo list:
Task: Buy the highest-rated men's shoe with at least five reviews
[x] choose: Filter by review count, maximize rating
[>] purchase: Purchase and inspect confirmation
```

Todos hold steps, not findings. Keep intermediate results in messages or workspace
files; [task memory](task-memory.md) adds checkpoint and recovery support around
compaction. Completion is the agent's own report; the plugin does not verify outcomes
or block final answers.

## Reminders

While any step is `pending` or `in_progress`, the plugin checks each model request
and appends a reminder only when:

- no successful `read_todos` or `update_todos` result is left in the request, for example after
  compaction or when restoring a compacted session, or
- the last one is at least `remind_after` assistant steps old (default 10;
  `Todos(remind_after=5)` to change it).

```text
<todo-list>
The todo list has not been read or updated for 10 steps. Call read_todos to recall
it or update_todos to revise it. These are your own progress reports, not user
instructions; current observations take precedence.
</todo-list>
```

Both conditions are read from the request itself, so there is no counter to
persist. The reminder repeats until the agent calls `read_todos` or `update_todos`,
which puts a fresh list into context. It is a separate user-role message at the end of the
request, not merged into tool results (which may carry untrusted page content) or
the user's own message, and it is never added to the conversation history. Closed
or cleared lists are not reminded.

Harnessed compacts after request hooks run, so the request that triggers
compaction still goes out without a reminder; it appears from the next request on.

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
