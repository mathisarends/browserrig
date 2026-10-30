# Telemetry: local agent traces with Docker

Browserrig uses Harnessed 0.6.0's native `OpenTelemetryTracer`. Phoenix displays
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
uv run --extra otel python -m examples.tracing_smoke --trace-content
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
uv run --extra openai --extra otel python -m examples.openai_agent --headed --trace-content
```

The example loads `.env` automatically. For a shorter task:

```powershell
uv run --extra openai --extra otel python -m examples.openai_agent --trace-content --url https://example.com --task "Describe this page."
```

| Flag | Effect |
| --- | --- |
| No trace flag | No tracing provider, exporter or OTel imports. |
| `--trace` | IDs, hierarchy, durations, outcomes, model/tool names and reported usage. |
| `--trace-content` | Also model messages/responses and tool arguments/results; implies `--trace`. |
| `--trace-max-content-length 65536` | Increase the per-field capture limit from 16,384 characters. |
| `--quiet` | Disable terminal JSON events; tracing continues independently. |

Content capture does not automatically redact arbitrary secrets. Prompts,
page content, form values, file contents and exception messages may be stored
in the Docker volume. Enable it for data you intend to keep in local traces.
Truncated input/output fields have `harnessed.input.truncated` or
`harnessed.output.truncated` attributes and a `text/plain` MIME type; complete
fields use JSON. Increase the limit when large DOM observations are cut off.

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

Select a **model** or **tool** span to inspect its input/output. In Harnessed
0.6.0, the root turn span has no input/output summary of its own. Each turn is a
separate trace; use `session.id` to follow turns in the same conversation.

These are agent-level traces. Individual CDP commands, browser network requests,
provider HTTP requests and provider-internal retries do not get separate spans.
Browser observations are visible inside model inputs when content capture is
enabled. Terminal events and durable session logs remain available separately.
Tool schemas and arbitrary provider settings are not included in the captured
model input; it is a portable conversation snapshot, not a raw HTTP request.

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
Harnessed plugin directly; `BrowserAgent` needs no telemetry-specific argument:

```python
import asyncio

from harnessed.integrations.opentelemetry import OpenTelemetryTracer
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from browserrig import BrowserAgent


async def run_traced(model):
    provider = TracerProvider(
        resource=Resource.create({
            "service.name": "browserrig",
            "openinference.project.name": "browserrig",
        })
    )
    try:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint="http://127.0.0.1:6006/v1/traces",
        )))
        agent = BrowserAgent(model=model, plugins=[OpenTelemetryTracer(
            tracer_provider=provider,
            capture_content=True,
            max_content_length=16_384,
        )])
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
| Empty input/output | Enable `--trace-content` and select a model/tool span rather than the root turn. |
| Capture ends partway through a field | Raise `--trace-max-content-length`; inspect the truncation attributes. |
| Missing optional dependency | Include `--extra otel` when syncing and running; include `--extra openai` for the OpenAI example. |

## References

- [Harnessed 0.6.0 tracing guide](https://github.com/mathisarends/harnessed/blob/v0.6.0/docs/guides/tracing.md)
- [Phoenix Docker and persistent SQLite setup](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [Phoenix 21 release notes](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v21.0.0)
- [Integration feedback collected for Harnessed](harnessed-telemetry-feedback.md)
