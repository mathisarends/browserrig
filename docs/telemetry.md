# Telemetry

[Back to README](../README.md)

Browserrig uses Harnessed's native `OpenTelemetryTracer`. Traces show turns, model
requests, tools, browser operations, timings and usage. Content capture and hook
instrumentation are opt-in.

## Start local traces

With Docker and Chrome installed, run from the repository root:

```powershell
docker compose -f compose.yml up -d --wait
uv sync --locked --extra otel
uv run --extra otel python -m examples.tracing_smoke --trace-content --trace-hooks
```

Open [Phoenix](http://127.0.0.1:6006) and select **browserrig** after the first trace
arrives. The smoke example uses a local page and scripted model; no API key is
needed. Compose stores traces in the `phoenix_data` volume and binds the service
to loopback with authentication disabled for local development.

For a real model, set `OPENAI_API_KEY` in `.env`:

```powershell
uv sync --locked --extra openai --extra otel
uv run --extra openai --extra otel python -m examples.openai_agent --headed --trace
```

| Flag | Effect |
| --- | --- |
| `--trace` | Names, IDs, durations, outcomes and reported usage |
| `--trace-content` | Also messages, responses, arguments/results and request definitions; implies tracing |
| `--trace-hooks` | Hook invocation spans; implies tracing |
| `--trace-max-content-length 65536` | Raise the per-field limit from 16,384 characters |
| `--quiet` | Disable terminal events independently of tracing |

Content capture can retain page text, credentials and file contents. CLI
`--trace-content` uses plain capture; application code can configure redaction.

## Read a trace

```text
harnessed.turn
  harnessed.step
    browserrig.*       observation, readiness, coordination
    harnessed.model    request, response, usage
    harnessed.tool
      browserrig.*     input, navigation, presentation, files
```

Use `session.id` to follow turns. `harnessed.outcome` and
`harnessed.output.partial` identify incomplete work. Model spans expose bounded
request tools/settings/output schemas when content capture is enabled.

For slow runs, compare model time, browser operation time and lock acquisition
(`BrowserCoordination.acquire`). Hook spans identify handlers with
`code.function.name` and `harnessed.hook.event/owner/priority`. Waterfalls include
the continuation they await, so nested durations overlap. Readiness includes
polling waits, and input spans include configured pacing. Individual CDP commands
and provider HTTP retries do not have separate spans.

Captured fields contain valid JSON; truncation is marked with
`harnessed.<field>.truncated`, `.original_length` and `.omitted_items`. Hook/content
instrumentation adds work: enable it when diagnosing those parts.

## Use in an application

Install `browserrig[otel]` and supply the native plugin. The application owns the
provider and shuts it down after its sessions close:

```python
import asyncio

from harnessed.integrations.opentelemetry import ContentCapture, OpenTelemetryTracer
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from browserrig import Agent


async def run_traced(model, token):
    provider = TracerProvider(resource=Resource.create({
        "service.name": "browserrig",
        "openinference.project.name": "browserrig",
    }))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint="http://127.0.0.1:6006/v1/traces",
    )))
    try:
        agent = Agent(model=model, plugins=[OpenTelemetryTracer(
            tracer_provider=provider,
            capture_content=ContentCapture.redacted(token),
        )])
        return await agent.run("Describe the current page.")
    finally:
        await asyncio.to_thread(provider.shutdown)
```

`ContentCapture.redacted(*secrets)` masks registered literals before truncation.
It does not scan the environment or Browserrig's `Secrets` plugin; recreate the
policy when credentials rotate. Exception text is disabled unless explicitly
enabled. A synchronous `content_filter` can replace or omit detached `TraceContent`
fields. Apply rules to every content kind that may contain the same value.
Explicit diagnostic `record(...)` attributes are outside content filtering.

Reuse a backend's existing provider when available; do not shut down a shared
provider per session. See [examples/telemetry.py](../examples/telemetry.py) for
application-managed startup and cleanup.

## Configuration and troubleshooting

Examples default to `http://127.0.0.1:6006/v1/traces`. Override with
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, or use the standard base
`OTEL_EXPORTER_OTLP_ENDPOINT`. Containers on the Compose network use
`http://phoenix:6006/v1/traces`. Standard OTLP headers and exporter settings apply.

| Symptom | Check |
| --- | --- |
| Docker unavailable | Start Docker and rerun Compose |
| No project/spans | Run the smoke example; inspect exporter stderr and endpoint |
| Empty messages/results | Enable content capture |
| Truncated fields | Inspect JSON markers or raise the content limit |
| Missing dependency | Include `--extra otel` when syncing and running |
| `401` from local Phoenix | Reapply `compose.yml`; remote services need their own authentication |

`docker compose -f compose.yml stop` retains data; `down` also retains the named
volume. `down -v` deletes the trace database. Export failures are logged without
failing the agent; verify ingestion in Phoenix.
