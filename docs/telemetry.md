# Telemetry: local agent traces with Docker

Browserrig uses Harnessed 0.14.0's native `OpenTelemetryTracer`. Phoenix displays
the agent's turns, model requests, tool calls, timing, outcomes and available
usage counters. Enable content capture to inspect what each model and tool
receives and returns.

## Start Phoenix

Run these commands from the repository root with Docker Desktop running:

```powershell
docker compose -f compose.yml up -d --wait
docker compose -f compose.yml ps
```

Open <http://127.0.0.1:6006> and select the **browserrig** project after the first
trace arrives. `compose.yml` pins Phoenix to `version-21.0.0`, stores its SQLite
database in the `phoenix_data` Docker volume and exposes its UI and OTLP/HTTP
collector on port 6006. No separate collector or database container is needed.

This configuration is for local development: authentication is disabled and the
published port is bound to `127.0.0.1`. Phoenix's own telemetry is disabled.
Phoenix 21 otherwise enables authentication by default when listening on a
non-loopback address inside the container.

## Try it without API keys

Chrome must be installed; the same browser discovery as other Browserrig
examples applies. Optionally set `BROWSERRIG_CHROME` in `.env`.

```powershell
uv sync --locked --extra otel
uv run --extra otel python -m examples.tracing_smoke --trace-content --trace-hooks
```

The smoke test starts a temporary HTTP server on loopback, launches headless
Chrome, navigates to the local test page and makes two scripted model calls.
It needs no provider SDK, API key, remote page or paid model call. Its trace
contains one turn, two steps, two model spans and one navigation tool span.
The printed session ID appears as `session.id` in Phoenix.

## Trace the OpenAI example

Set `OPENAI_API_KEY` in `.env` as described in the repository's quick start:

```powershell
uv sync --locked --extra openai --extra otel
uv run --extra openai --extra otel python -m examples.openai_agent --headed --trace-content --trace-hooks
```

The example loads `.env` automatically. For a shorter task:

```powershell
uv run --extra openai --extra otel python -m examples.openai_agent --trace-content --url https://example.com --task "Describe this page."
```

| Flag | Effect |
| --- | --- |
| No trace flag | No tracing provider, exporter or OTel imports. |
| `--trace` | IDs, hierarchy, durations, outcomes, model/tool names and reported usage. |
| `--trace-content` | Also turn summaries, model messages/responses, tool arguments/results and request definitions/settings/schemas; implies `--trace`. |
| `--trace-hooks` | Add invocation spans for every dispatched hook to diagnose harness/plugin overhead; implies `--trace`, without capturing content. |
| `--trace-max-content-length 65536` | Increase the per-field capture limit from 16,384 characters. |
| `--quiet` | Disable terminal JSON events; tracing continues independently. |

Content capture does not automatically redact arbitrary secrets. Prompts,
page content, form values, file contents and exception messages may be stored
in the Docker volume. Enable it for data you intend to keep in local traces.
All content fields, including truncated fields, contain valid `application/json`.
Truncation sets `harnessed.<field>.truncated`, `.original_length` and `.omitted_items`
attributes. Parse the JSON and inspect those markers; very small limits may retain
only a placeholder. Each field has its own character budget.

## Read a trace

Open the project, select a trace and expand its spans:

```text
harnessed.turn                 session.id, turn ID, outcome
  harnessed.step
    harnessed.model            input messages, response, usage
    harnessed.tool             tool.name, arguments, result, status
  harnessed.step
    harnessed.model            updated observations and final response
```

The root **turn** span shows accepted user input and the final or partial answer,
including accepted structured output. `harnessed.outcome` and
`harnessed.output.partial` distinguish incomplete results. Each turn is a separate
trace; use `session.id` to follow turns in the same conversation.

**Model** spans also expose independently bounded `request.tools.value`,
`request.settings.value` and `request.output_schema.value` fields when content
capture is enabled. These describe the portable resolved request; provider-internal
HTTP bodies, retries and defaults remain inside the model span.

### Browser time

Browserrig uses `traced`, `span` and `record` from the public `harnessed.tracing`
API. Library spans use their full Python name, beginning with `browserrig.`;
Harnessed runtime spans retain `harnessed.`. Decorated functions carry
`code.function.name`, `code.file.path` and `code.line.number`, pointing at the
installed source. Arguments and return values are not captured by decorators.

```text
harnessed.step
  harnessed.hook                              with --trace-hooks
    browserrig.observation.plugin.BrowserPerception.capture
      browserrig.core.BrowserCoordination.acquire
      browserrig.readiness.wait.wait_for_page
      browserrig.observation.capture.capture_observation
        browserrig.browser.tab.Tab.frames
        browserrig.observation.extraction.extract
          browserrig.observation.extraction._snapshot / _focused
          browserrig.observation.extraction._Assembler.run
          browserrig.observation.extraction.accessibility.chrome_names
        browserrig.browser.images.screenshot
  harnessed.model
  harnessed.tool
    harnessed.hook                            ExecuteTool middleware
      browserrig.tools.execution.Actions.run
        browserrig.core.BrowserCoordination.acquire
        browserrig.tools.execution.Actions._prepare
        browserrig.operation
          browserrig.tools.targeting.Targeting.locate
          browserrig.input.mouse.Mouse.click
        browserrig.tools.execution.Actions._settle
```

File tools add `browserrig.files.system.FileSystem.*` and
`browserrig.files.transfer.FileTransfer.*` spans. `FileReader.read` runs below
`FileSystem.read_file` even across its worker thread, with format and extraction
cache-hit metadata. JavaScript evaluation, navigation, reload and iframe
presentation also have their own spans. Readiness records `polls`, `probe_ms`,
status and phase; lock acquisition records `contended` separately from work while
holding the lock.

### Find a bottleneck

Run the smoke test with `--trace-hooks`, then repeat the real task with the same
flag. In Phoenix, expand the waterfall and compare:

- `harnessed.model`: model/provider time, including provider retries.
- `harnessed.hook`: invoked handler time. Inspect `code.function.name`,
  `harnessed.hook.event`, `.owner` and `.priority` to identify the plugin.
- `browserrig.*`: readiness, extraction, browser input, presentation and file work.
- `BrowserCoordination.acquire`: time waiting for another operation to release control.

A Waterfall hook includes the downstream continuation it awaits. Nested hook,
tool and browser durations therefore overlap; do not add them as independent
costs. To estimate a span's own time, subtract the union of its child intervals,
counting overlapping intervals once. Large remaining hook time points to work in
that handler; large remaining step/turn time is a place to investigate further,
not proof of CPU overhead. It can include scheduling, serialization or work not
covered by child spans. Readiness duration beyond `probe_ms` includes deliberate
polling waits, and pointer/keyboard spans include configured input pacing.

Hook spans are opt-in because high-volume events add export and instrumentation
cost. Compare representative runs with and without `--trace-hooks`; use
`--trace-content` separately when diagnosing request content, since capture and
serialization also add work. Individual CDP commands, network requests and
provider HTTP retries have no separate spans. Browser startup before an active
tracer and independently created background tasks are not automatically attached
to a turn.

## Configure the exporter

The examples default to `http://127.0.0.1:6006/v1/traces`. Uncomment the optional
settings in `.env.example` when copying them into your `.env`:

```dotenv
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:6006/v1/traces
OTEL_SERVICE_NAME=browserrig
PHOENIX_PROJECT_NAME=browserrig
```

`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` specifies the complete traces URL. The
standard `OTEL_EXPORTER_OTLP_ENDPOINT` can instead specify a base URL; the HTTP
exporter appends `/v1/traces`. The signal-specific endpoint takes precedence.
Standard OTLP headers, compression, timeout and batch processor environment
variables are handled by the OTel SDK. This integration uses HTTP/protobuf.

For an application running in another container on the same Compose network,
use `http://phoenix:6006/v1/traces` as its traces endpoint. Keep the loopback URL
for an agent running directly on your host.

## Use it in your own application

Install `browserrig[otel]` plus the extra for your model provider. Supply the
Harnessed plugin directly; `Agent` needs no telemetry-specific argument:

```python
import asyncio
import os

from harnessed.integrations.opentelemetry import ContentCapture, OpenTelemetryTracer
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from browserrig import Agent


async def run_traced(model):
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "browserrig",
                "openinference.project.name": "browserrig",
            }
        )
    )
    try:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint="http://127.0.0.1:6006/v1/traces",
                )
            )
        )
        agent = Agent(
            model=model,
            plugins=[
                OpenTelemetryTracer(
                    tracer_provider=provider,
                    capture_content=ContentCapture.redacted(
                        os.environ["OPENAI_API_KEY"]
                    ),
                    max_content_length=16_384,
                    trace_hooks=True,
                )
            ],
        )
        async with agent.session() as session:
            return await session.run("Describe the current page.")
    finally:
        await asyncio.to_thread(provider.shutdown)
```

The application owns its provider. Reuse an existing provider when integrating
into a backend, and shut it down once after its active sessions close. Do not
flush after every model call or shut down a shared provider per session. The
examples keep this startup/cleanup code in `examples/telemetry.py`; Browserrig
does not install a global provider or add a second tracer abstraction.

### Redaction and application filtering

`ContentCapture.redacted(*secrets)` accepts literal strings and wrappers such as
Pydantic `SecretStr`. Registered values are masked in model inputs/outputs, tool
arguments/results, turn summaries and request definitions/settings/schemas before truncation. Execution and session
history retain their original values. Exception messages remain disabled unless
`include_exception_messages=True`; `capture_content=True` retains the existing plain
opt-in, including exception text. CLI `--trace-content` uses that boolean behavior.
Register credentials explicitly: Harnessed does not scan the environment or
Browserrig's `Secrets` plugin. Recreate policies when credentials rotate; encoded
values and unregistered secrets require application rules.

The shared example helper also accepts the native policy and a synchronous
`content_filter`. For example, omit a tool's result field:

```python
from harnessed.integrations.opentelemetry import (
    ContentCapture,
    TraceContentKind,
)
from examples.telemetry import tracing_plugins


def filter_content(content):
    if (
        content.kind is TraceContentKind.TOOL_RESULT
        and content.tool_name == "read_file"
    ):
        return None
    return content


async with tracing_plugins(
    capture_content=ContentCapture.redacted(token),
    content_filter=filter_content,
) as telemetry:
    agent = Agent(model=model, plugins=telemetry)
    await agent.run("Inspect the page.")
```

Filters receive detached `TraceContent` values and may return a replacement or
`None` to omit the field. Registered literals are masked in replacements too.
The filter kinds now include `TURN_INPUT`, `TURN_OUTPUT`, `MODEL_TOOLS`,
`MODEL_SETTINGS` and `MODEL_OUTPUT_SCHEMA`. Tool results can also appear in model
history and turn output, while tool arguments can appear in model output. Apply
rules to every kind that can carry a copy when omitting a value everywhere.
Explicit `record(...)` attributes are metadata outside content filtering; record
only diagnostic counters and flags. Failed filters omit content with a marker
and preserve the agent outcome. Optional OTel imports remain lazy when tracing is off.

## Stop, retain data and troubleshoot

```powershell
docker compose -f compose.yml stop
docker compose -f compose.yml up -d --wait
docker compose -f compose.yml logs --tail 100 phoenix
```

`stop` and `down` retain the named volume. **`docker compose down -v` deletes
the trace database.**

| Symptom | Check |
| --- | --- |
| Cannot connect to the Docker daemon | Start Docker Desktop, then rerun `docker compose up -d --wait`. |
| Port 6006 is already in use | Stop the conflicting service, or change the published host port and the exporter URL together. |
| No `browserrig` project or spans | Run the smoke test with `--trace-content`; check stderr and the endpoint. The project is created on first ingestion. |
| `401 Unauthorized` from local Phoenix | Reapply this `compose.yml`; it explicitly disables auth for local use. Remote authenticated endpoints need OTLP auth headers. |
| Agent succeeds but no trace arrives | OTel export failures are logged to stderr and do not fail the agent. Verify ingestion in Phoenix; process exit alone is not proof. |
| Empty input/output | Enable `--trace-content`; turn, model and tool content is opt-in. |
| Capture ends partway through a field | Parse the JSON and inspect truncation markers; raise `--trace-max-content-length`. |
| Missing optional dependency | Include `--extra otel` when syncing and running; include `--extra openai` for the OpenAI example. |

## References

- [Harnessed 0.14.0 tracing guide](https://github.com/mathisarends/harnessed/blob/v0.14.0/docs/guides/tracing.md)
- [Phoenix Docker and persistent SQLite setup](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [Phoenix 21 release notes](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v21.0.0)
- [Integration feedback collected for Harnessed](harnessed-telemetry-feedback.md)
