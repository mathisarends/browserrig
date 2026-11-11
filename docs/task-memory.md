# Task working memory

The default browser pack uses `TaskMemory` for context compaction. The agent keeps
its working state in `notes/task_state.md` with the existing `write_file`,
`edit_file` and `read_file` tools. The file is the canonical memory; its contents
are never automatically injected into every request. TODOs remain a separate,
optional plan, recalled with `read_todos`.

The fixed guidance asks the agent to save requirements, findings with exact IDs
and sources, decisions, confirmed versus unconfirmed actions, open checks and the
next step. Important findings and writes should be recorded as work progresses.
Large tables or documents stay in linked files. Notes for a new assignment replace
unrelated old task notes. Before reporting success or giving up, the agent is
asked to compare requirements against current visible state, including source,
destination and saved result for writes. This is guidance, not a separate judge
or a mechanical guarantee of task completion.

## Checkpoint and recovery

1. At 70% of a known context window, or 70,000 estimated tokens when the window
   is unknown, a short reminder asks the same agent to save its working state.
   It is sent once per compaction cycle, not on every step.
2. If native compaction is already due, it may be deferred for that request only,
   provided estimated use is below 90% of a known window. The next request follows
   the ordinary compaction policy even if the agent ignored the checkpoint. Native
   emergency compaction always takes precedence. Checkpoint work consumes the
   existing step, token and timeout budgets; it adds no nested agent run.
3. The ordinary summarizer runs, with part of its existing output allowance
   reserved for a short handover prefix. This prefix tells the agent to call
   `read_file` on the memory file and reaches the **first compacted request**.
   The file itself is not loaded into the summary. Linked artifacts are read only
   as needed. The summarizer's usage remains part of native compaction accounting.
4. A successful, complete read of the memory file acknowledges recovery. A missing
   file, ignored hint or partial read leaves recovery pending. The agent can
   reconstruct missing notes from the summary and fresh observations.

No new checkpoint or resume request is injected when fewer than three steps
remain, or on the reserved final-answer step. An inline summary handover may still
be present. With an unusually small summary allowance that cannot accommodate the
prefix and useful summary text, a short recovery hint is sent on the next eligible
request instead. There is no repeating recovery-message loop.

Keep the memory file nonempty and at most **16,000 UTF-8 bytes**, and read it in
one request from offset zero. Other files are not subject to that memory limit.
Empty or oversized memory files do not count as a saved checkpoint. This bounds
fingerprinting work and keeps a normal `read_file` response sufficient for recovery.
The harness checks the file operation, not the accuracy or completeness of the
agent's notes. Treat notes as historical data; current observations take precedence.

## Configuration and persistence

`TaskMemory` fills the same slot as native `ContextCompaction` and supports its
`trigger`, `llm`, replacement `prompt` (string or sync/async factory), custom
`summarizer`, `keep_last_steps`, `target_ratio` or `target_tokens`, and optional
`max_summary_tokens` options. Custom summarizers accept a `CompactionRequest` and
return `Summary`; `summarizer` cannot be combined with `llm` or `prompt`.
The default retains the last two complete model/tool steps across turns. Summary
budgets are derived automatically unless an explicit ceiling is configured.
Complete output is never sliced; Harnessed may make one further summarization
attempt and accounts for usage from rejected candidates too.

```python
from browserrig import Agent, Files, LocalWorkspace, TaskMemory, Todos, WindowRatio

agent = Agent(
    model=model,
    plugins=[
        Files(LocalWorkspace(".browserrig/research")),
        Todos(),
        TaskMemory(
            path="notes/task_state.md",
            warn_at=0.65,
            fallback_tokens=60_000,
            trigger=WindowRatio(0.8),
            keep_last_steps=4,
        ),
    ],
)
```

For a custom earlier compaction trigger, lower the warning threshold too; unrelated
custom triggers may compact without a prior checkpoint. A provider context-limit
error or sudden growth can also force emergency compaction before a checkpoint.
`warn_at` uses the model's reported window and any `ContextBudget` limit; configure
the model's window when available. A separate per-run context-window override can
force earlier native compaction. Safety does not depend on checkpoint delivery.

Pass `ContextCompaction(...)` to use plain native compaction without this protocol.
`without=(ContextCompaction,)` removes the default `TaskMemory` as well. Without
workspace file tools, there are no checkpoint or recovery requests; compaction
continues normally. A plain Harnessed agent can mount `TaskMemory`, `Files` and
`WorkspaceTools` together.

The file lives in the configured workspace and outlives context compaction. The
default `Files()` chooses a new local directory per session. To resume after a
restart, reuse the same explicit workspace **and** restore the session with a
`SessionState` or configured session store. The store keeps only handover metadata,
including the file's SHA-256 revision and pending recovery; it does not duplicate
the notes. A fresh session starts with fresh metadata, even if it shares a directory.

## Traces and events

`TaskMemoryEvent` records `checkpoint_requested`, `saved`, `compacted`,
`restore_requested`, `restored`, `partial_read` and `unavailable`. Each receipt
contains the configured path, SHA-256 revision, compaction ID when applicable,
checkpoint status and pending recovery. The `compacted` receipt says whether a
nonempty bounded write was observed since the latest checkpoint request or prior
compaction. It does not certify freshness or correctness. Reads and writes also
retain the ordinary workspace events and tool results.

Each receipt produces a `browserrig.memory` span. In Phoenix, filter this name
and inspect `action`, `revision`, `compaction_id`, `checkpoint_saved` and
`restore_pending` (exported with Harnessed's attribute prefix). A one-step deferral
has a `browserrig.memory.defer_compaction` span. Receipt metadata contains no note
body; ordinary model/tool content follows the configured trace content policy.

For application code, `session.scope[TaskMemory].current` returns an immutable
Pydantic `TaskMemoryState`. Use the correlated receipts to distinguish a missing
checkpoint, a pending read and a recovered file. These are observable operations;
they do not prove that the model used or understood the facts. Compare benchmark
success, token use and repeated work in separately labeled runs before claiming an
improvement. No new paid evaluation is required to enable the protocol.

`browserrig.Agent` applies the shared GPT-6.1 Terra application profile for both
OpenAI API and Codex subscription models, including prewrapped models: 256,000
tokens of context, an 8,192-token output reserve, two retained steps, a 40% target
and an 8,192-token summary ceiling. With this profile the checkpoint starts at
179,200 tokens and compaction at 204,800 tokens, both including reserved output.
The post-compaction input target is 102,400 tokens and is best effort. Explicit
budget services and compaction plugins override the defaults. Benchmarks use
the same agent path and record the profile in each result file.

Harnessed 0.16 uses conversation state format 3 and audit envelope version 6.
Older states and audit logs cannot be loaded directly; retain the original
application environment to read them and use new stores for this version.

The integration wraps the compaction policy and summarizer of pinned Harnessed
0.16.0. This narrow internal boundary is covered by real compaction, recovery,
budget and session-store tests; review it when upgrading Harnessed.
