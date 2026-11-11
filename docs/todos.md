# Task todos

[Back to README](../README.md)

`Todos()` adds an optional session plan through `update_todos` and `read_todos`.
It works with Browserrig or a plain Harnessed agent, without a browser or model
calls of its own:

```python
from browserrig import Agent, Todos

agent = Agent(model=model, plugins=[Todos(remind_after=10)])
```

## Update and recall

`update_todos(task, todos)` replaces the entire list atomically. Keep IDs stable;
omitted steps are removed, and `todos=[]` clears it. `read_todos()` returns the
saved list, including closed steps, or `No todo list saved.`

```json
{
  "task": "Compare delivery options",
  "todos": [
    {"id": "research", "title": "Collect prices and sources", "status": "completed"},
    {"id": "compare", "title": "Compare totals and delivery dates", "status": "in_progress"}
  ]
}
```

Status is `pending`, `in_progress`, `completed` or `cancelled`; at most one step
can be in progress. Limits are 20 steps and 240 characters per title/task. Invalid
updates preserve the previous list. `Todo` and `TodoList` are the exported models.
Completion is the agent's report; the plugin does not verify outcomes or block
final answers. Store findings in files or messages, with [task memory](task-memory.md)
for recovery around compaction.

## Reminders and persistence

While steps remain open, a `PrepareRequest` hook adds a short reminder if no
successful read/update remains in context or the latest one is `remind_after`
steps old. The reminder asks the agent to recall the plan; it contains no plan
contents and is not saved to conversation history. Closed lists get no reminders.

The plan survives turns, compaction and restored session state. Reopening by ID
requires a configured [session store](agent-guide.md#saving-and-restoring-sessions).
`session.scope[Todos].current` exposes `TodoList | None` to the application. A fresh
session starts empty.
