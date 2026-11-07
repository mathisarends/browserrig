# Human handoff

`HumanHandoff` is an opt-in plugin for login, 2FA and other steps a person needs
to complete in the browser. Add it to the `plugins` of `browserrig.Agent`,
to `browser_plugins(...)`, or to a plain Harnessed `Agent`'s plugin list. Without the
plugin, no handoff tool, prompt section or pause tracking is added.

```python
from browserrig import Agent, Chrome, HandoffStatus, HumanHandoff, HumanResponse
from browserrig.events import HandoffRequestedEvent

async def ask_human(request: HandoffRequestedEvent) -> HumanResponse:
    # Your host UI shows request.reason and request.expected_state, then waits
    # for its Done / Decline controls. It can use request.handoff_id to correlate
    # the response with this request.
    return await ui.request_browser_control(request)

handoff = HumanHandoff(
    ask=ask_human,
    timeout=900,
    track_pauses=True,
    history_limit=5,
)
agent = Agent(
    model=model,
    browser=Chrome.launch(url=url, headless=False),
    plugins=[handoff],
)
```

`ui`, `model` and `url` above are supplied by your application. The callback owns
the UI and returns `HumanResponse()` when the person selects Done, or
`HumanResponse(status=HandoffStatus.DECLINED)` when they decline. A note is optional:
`HumanResponse(note="Signed in and confirmed 2FA")`. No text entry is required.
Keep credentials out of notes. A remote browser viewer can be used instead of
launching a headed browser.

The model calls `request_human(reason=..., expected_state=...)`. The tool waits
inside the current step; do not call `session.pause()` from its callback, since
pause waits for that step to finish. The callback timeout is independent of the
ordinary tool timeout. On timeout or abort, the callback is cancelled; host code
should clean up its UI and ignore late responses for that handoff ID.

The tool is sequential and ends the action chain. Later calls from the same
model response are skipped so they cannot act on assumptions from before the
handoff. Asking for human input is registered as a readonly tool; explicit
Harnessed approval policies can still deny it. Browser mutations during the
handoff belong to the human and are not dispatched through agent action tools.

## What the agent receives

The JSON tool result follows the exported Pydantic `HandoffReceipt` model. It
contains the request, status, optional human note, measured changes and current
URL. `HandoffStatus` is a `StrEnum` with `DONE`, `DECLINED`, `TIMEOUT`, `CANCELLED`,
`FAILED` and host-pause `RESUMED` members. Their JSON values remain `"done"`,
`"declined"`, `"timeout"`, `"cancelled"`, `"failed"` and `"resumed"`. Human callbacks
can report only `DONE` or `DECLINED`; the runtime determines the other outcomes.
Completion reports are historical claims; they do not prove that login succeeded
or that the same session is still authenticated.

Before and after snapshots compare the active tab, URL, document, title, open
tabs and page content. Intermediate tab-open, tab-close, dialog and download
events are counted, including a popup opened and closed during login. Password
field values are never part of the receipt. URL queries, fragments and userinfo
are omitted. When `Secrets` is mounted, its known values are also redacted from
receipts, events and the saved handoff context.

After control returns, the next step receives a complete, fresh browser
observation. Old snapshot and coordinate state are invalidated. The model must
verify the expected state there before continuing or repeating a submission.
If a comparison capture fails, the receipt explicitly says inspection is still
needed. Hints are withheld during human control and pending action checks are
discarded; intermediate effects are reported in the handoff receipt instead.

Applications inspect typed records through the mounted plugin:

```python
async with agent.session() as session:
    await session.run("Continue after login")
    handoff = session.scope[HumanHandoff]
    history = handoff.history  # tuple[HandoffReceipt, ...]
    if history and history[-1].status is HandoffStatus.CANCELLED:
        print("Handoff cancelled", history[-1].human_note)
```

`history` is an immutable snapshot of the latest `history_limit` redacted receipts,
ordered oldest first. A new session starts with an empty tuple. Restoring a
`SessionState` or reopening a stored session restores its receipts before the
first turn; retaining a tuple does not change it when new handoffs finish.

The plugin serializes these records at the Harnessed storage and model-input
boundary. The tool returns one JSON receipt, and changes to recent history are
delivered by a `PrepareRequest` hook as request-only user messages. The latest history survives
compaction independently of its summary. The fixed system prompt is unchanged.
Application code does not need a context key, JSON parsing or an SDK persistence
service. This retains handoff reports; it does not restore browser cookies or an
authenticated browser session.

## Host-initiated pause

With `track_pauses=True`, the same plugin remembers the last delivered agent
observation when the host pauses the session. The receipt labels that baseline;
it can predate the last completed action. Before any agent observation, it reports
that no baseline is available. After resume, it records a receipt before the next model
step, with `source="pause"` and `status=HandoffStatus.RESUMED`. The callback is not
called, and no manual `steer()` is needed to explain external browser changes.
Set `track_pauses=False` to keep only the model-requested handoff tool.

`HandoffRequestedEvent` and `HandoffFinishedEvent` are available from
`browserrig.events`. `Activity` records model-requested human waiting as
`ActivityKind.HANDOFF`, separately from tool execution. Host pauses retain the
existing `ActivityKind.PAUSED` interval.
