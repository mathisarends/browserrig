# Human handoff

[Back to README](../README.md)

`HumanHandoff` adds optional browser takeover for login, 2FA and other human steps.
The plugin co-locates the handoff tool, instructions, pause tracking and receipt
context. Mount it in Browserrig or Harnessed alongside the browser capabilities:

```python
from browserrig import Agent, Chrome, HumanHandoff, HumanResponse
from browserrig.events import HandoffRequestedEvent


async def ask_human(request: HandoffRequestedEvent) -> HumanResponse:
    return await ui.request_browser_control(request)


agent = Agent(
    model=model,
    browser=Chrome.launch(url=url, headless=False),
    plugins=[HumanHandoff(ask=ask_human, timeout=900, history_limit=5)],
)
```

The application supplies `ui`, `model` and `url`; a remote viewer can replace the
headed browser. Show `request.reason` and `expected_state`, then return
`HumanResponse()` for Done or `HumanResponse(status=HandoffStatus.DECLINED)` for
Decline. An optional `note` can explain the result. Keep credentials out of notes.

## Return context to the agent

The model calls `request_human(reason=..., expected_state=...)` and waits inside
the current step. Do not call `session.pause()` from the callback: pause waits for
that step to finish. On timeout or abort, the callback is cancelled; clean up the
UI and ignore late responses for that `handoff_id`.

A typed `HandoffReceipt` records the request, outcome, note, current URL and
measured before/after browser changes. The next step gets a fresh observation;
old references/coordinates are invalidated and later calls in the old action
chain are skipped. The agent must verify the expected state before continuing.
A human's Done report does not establish that login or submission succeeded.

Recent redacted receipts are delivered through `PrepareRequest` as request-only
messages and survive compaction and restored session state. They do not restore
cookies or an authenticated browser. Password values and URL queries/fragments/
userinfo are omitted; configured `Secrets` values are redacted too.

Applications read `session.scope[HumanHandoff].history`, an immutable tuple of the
latest receipts. Callbacks report `HandoffStatus.DONE` or `DECLINED`; the runtime
also records `TIMEOUT`, `CANCELLED`, `FAILED` and host-pause `RESUMED`.

## Host-initiated pause

`track_pauses=True` (default) records changes between the last delivered browser
observation and resume, before the next model step. The receipt labels that
baseline, which may predate the final action. No callback or manual steering is
needed. Set `track_pauses=False` for model-requested handoffs only.

`HandoffRequestedEvent` and `HandoffFinishedEvent` come from `browserrig.events`.
`Activity` separates human waiting from tool execution and ordinary host pauses.
