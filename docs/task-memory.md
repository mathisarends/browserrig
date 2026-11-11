# Task working memory

[Back to README](../README.md)

The default browser pack uses `TaskMemory` for context compaction. The agent keeps
working notes in `notes/task_state.md` through ordinary file tools. Notes hold
requirements, findings and sources, confirmed actions, open checks and the next
step; large artifacts stay in linked files. The memory file is read on recovery
rather than injected into every model request. [Todos](todos.md) track the plan
separately.

## Checkpoint and recovery

1. At 70% of a known context window, or 70,000 tokens when unknown, a reminder asks
   the agent to save its working state. It appears once per compaction cycle.
2. Native compaction can be deferred by one request below 90% of a known window.
   Emergency compaction takes precedence; checkpoint work uses the existing budget.
3. Compaction includes a short handover asking the agent to read its notes in the
   first compacted request. The file contents are not loaded into the summary.
4. A complete read acknowledges recovery. Missing or partial notes leave recovery
   pending, and the agent can reconstruct them from the summary and observations.

Keep the file nonempty and at most 16,000 UTF-8 bytes, readable in one call from
offset zero. The runtime checks file operations, not the correctness of notes.
Current observations take precedence over saved claims. Near the step limit,
checkpoint/recovery requests are suppressed to leave room for the final answer.

## Configuration and persistence

```python
from browserrig import Agent, Files, LocalWorkspace, TaskMemory, WindowRatio

agent = Agent(
    model=model,
    plugins=[
        Files(LocalWorkspace(".browserrig/research")),
        TaskMemory(
            path="notes/task_state.md",
            warn_at=0.65,
            trigger=WindowRatio(0.8),
            keep_last_steps=4,
        ),
    ],
)
```

`TaskMemory` fills the `ContextCompaction` slot and accepts native summarizer,
trigger and budget options. Default compaction starts at 80% of the model window,
or 100,000 tokens when unknown, retaining two steps. A custom earlier trigger
should use an earlier warning threshold too.

Pass `ContextCompaction(...)` for plain native summarization;
`without=(ContextCompaction,)` removes the default task memory. Without workspace
file tools, compaction continues without checkpoint/recovery requests.

GPT-6.1 Terra uses a shared application profile: 256,000 context tokens, an 8,192
token output reserve, two retained steps, a 40% post-compaction target and an 8,192
token summary ceiling. Explicit budgets and compaction plugins override defaults.

For recovery after a restart, reuse the workspace and restore the session.
Persisted metadata records revisions and recovery status; it does not copy the
notes into the session store. A fresh session starts with fresh metadata.

## Observe memory operations

`session.scope[TaskMemory].current` returns immutable `TaskMemoryState`.
`TaskMemoryEvent` records checkpoint requests, saves, compactions, restore
requests, complete/partial reads and unavailable notes, with path, revision and
compaction ID. Traces use `browserrig.memory` spans. These receipts establish
which operations occurred, not whether the agent understood or verified the notes.
