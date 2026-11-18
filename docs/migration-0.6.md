# Migrate from 0.5.x to 0.6.0

[Back to README](../README.md) · [Release notes](../CHANGELOG.md#060-2026-11-16)

Browserrig 0.6.0 pins Harnessed and all provider/MCP/OTel extras to 0.18.0.
Upgrade Browserrig and the extras your application uses together:

```sh
python -m pip install --upgrade "browserrig[openai]==0.6.0"
```

## Name duration units explicitly

Numeric Browserrig durations now name their units; their values remain seconds.
Old Python keyword names and old event payload field names are removed.

| 0.5.x | 0.6.0 | Applies to |
| --- | --- | --- |
| `timeout` | `timeout_seconds` | `Chrome.launch`/`connect`, low-level `Launch`/`Connect`, `HumanHandoff`, `Tab.evaluate`, `Tabs.opened_since`, `execute_javascript` |
| `ReadinessOptions.timeout` | `ReadinessOptions.timeout_seconds` | Readiness configuration |
| `poll_interval` | `poll_interval_seconds` | `ReadinessOptions` |
| `typing_interval` | `typing_interval_seconds` | `HumanMotor` |
| `duration` | `duration_seconds` | Input paths, drag APIs and tools, readiness reports, browser and choreography events |
| `original_duration` | `original_duration_seconds` | `RecordingResult` |
| `duration` | `duration_seconds` | `RecordingResult` |

For example, `Chrome.launch(timeout=30)` becomes
`Chrome.launch(timeout_seconds=30)`. Update custom viewers, serialized payload
readers and model tool-call producers to the new names. The built-in overlay and
terminal consumers are already migrated. Fields ending in `_ms` and upstream
CDP, HTTP and animation APIs retain their existing units and names.

## Select observation text

Version 0.6.0 removed `sparse_text_chars` and introduced `text=PageText.*`.
In the current API, use `page_prose` to select the text mode.

```python
from browserrig import DomCapture

inline = DomCapture(page_prose="inline", max_text_chars=3000)
sparse = DomCapture(page_prose="sparse", max_text_chars=1000)
controls_only = DomCapture(page_prose="off", headings=False, landmarks=False)
```

Use `page_prose="off"` for controls-only capture. Turn off `headings` and
`landmarks` to omit those structural elements too. Controls keep their labels,
and dialogs and cookie banners remain grouped. Sparse capture uses
`max_text_chars` as its prose budget. Use `DomRenderer()` with explicit DOM capture
when delivering text. WebArena exposes the same switches through `--page-text`,
`--no-headings` and `--no-landmarks`.

## Read model-written labels directly from host events

Labels are optional. Add `ActionLabels()` to request them and receive redacted
envelopes; existing tool implementations need no changes:

```python
from browserrig import ActionLabels, Agent
from browserrig.choreography import ToolCallPhase, ToolCallPresentedEvent

agent = Agent(plugins=[ActionLabels()])

async with agent.session() as session:
    async with session.stream("Read the annual report") as stream:
        async for event in stream:
            match event:
                case ToolCallPresentedEvent(phase=ToolCallPhase.REQUESTED) as event:
                    print(event.envelope.action_label)
```

The plugin registers the `ActionLabel` envelope for all tools, including foreign
plugins and MCP tools. Use `ActionLabels()` as the complete opt-in rather than
also registering `CallEnvelope(ActionLabel)` yourself. For native Harnessed,
compose `plugins=[browser_pack(), ActionLabels()]`.

`ToolCallPresentedEvent` is transient and carries requested/finished phases,
`call_id`, `tool_name` and the finished `ToolStatus`. Missing or invalid labels
become an empty string. Secret redaction happens before emission, so the host
needs no helper or session scope to read `event.envelope.action_label`, even
after the session closes. These events also appear in
`session.subscribe(transient=True)` and do not change overlay captions.
Harnessed's original tool-call events retain their raw replay contract.

Browser action lifecycle events now carry `call_id` and `label`, allowing hosts
to join actions to calls. Without model labels, the label is the tool name;
`Actions.run(label=...)` names explicitly managed operations.

## Attached downloads and compatibility

Hosts that own an attached browser's download policy can supply
`Chrome.connect(downloads=...)` with a `DownloadSource` to relay download events
without transferring file ownership. Existing connections need no new argument.
See [files and events](files-and-events.md) for the adapter contract.

State/checkpoint format 3 and audit envelope 6 remain unchanged from Browserrig
0.5.x. Keep stores from older incompatible Harnessed versions separate. See
[development](development.md#compatibility-and-coverage) for persistence caveats
and [choreography](browser-choreography.md#model-written-action-labels) for the
complete host-event contract.
