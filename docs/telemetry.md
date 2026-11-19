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
| `--trace-max-content-length 65536` | Raise the 16,384-character limit for content fields and model message parts |
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
`harnessed.output.partial` identify incomplete work. With content capture enabled,
Harnessed 0.20 model spans expose `llm.input_messages`, `llm.output_messages`,
`llm.tools`, and `llm.invocation_parameters` using OpenInference. Input spans show
new messages by default. `harnessed.input_messages.inherited` counts messages
already shown on earlier spans. Use `full_input_messages=True` on the tracer to
include the full message list on each model span.

For slow runs, compare model time, browser operation time and lock acquisition
(`BrowserCoordination.acquire`). Hook spans identify handlers with
`code.function.name` and `harnessed.hook.event/owner/priority`. Waterfalls include
the continuation they await, so nested durations overlap. Readiness includes
polling waits, and input spans include configured pacing. Individual CDP commands
and provider HTTP retries do not have separate spans.

JSON content fields mark truncation with `harnessed.<field>.truncated`,
`.original_length` and `.omitted_items`. On model spans, text and tool arguments
are limited individually and include an inline truncation marker.

## Screenshot and action attributes

Start with `browserrig.operation` and find `browserrig.screenshot.id` on a
`browserrig.observation` span with outcome `delivered`. Join that observation's
`browserrig.request.id` to `harnessed.request_id` on a `harnessed.model` span.
In Phoenix, the screenshot caption and image appear together in the model
input. Harnessed exports each distinct image once per session. If the image
reappears, its placeholder gives the digest and the first model span ID. Image
export requires content capture, allows up to 5 MiB per image by default, and
respects the tracer's content filter. The Browserrig spans carry metadata.

The following `browserrig.*` keys are stable. Fields appear when applicable.

| `browserrig.observation` attribute | Value |
| --- | --- |
| `browserrig.observation.id` | ID of the captured snapshot |
| `browserrig.tab_id`, `browserrig.document_id`, `browserrig.url` | Page identity at capture |
| `browserrig.screenshot.id` | Browserrig screenshot ID, also shown in the model's caption |
| `browserrig.screenshot.asset_id` | SHA-256 of the PNG bytes after applying marks and cursor rendering, matching Harnessed's `AssetRef.sha256` |
| `browserrig.screenshot.width`, `browserrig.screenshot.height` | Image dimensions in pixels |
| `browserrig.screenshot.scale` | Delivered image pixels per viewport CSS pixel, including crop zoom |
| `browserrig.screenshot.device_scale` | Chrome's capture density before normalization, when available |
| `browserrig.screenshot.reused_id` | Earlier screenshot kept when the new capture is unchanged |
| `browserrig.request.id` | Final model request that determined inclusion |
| `browserrig.observation.outcome` | `delivered`, `skipped_unchanged`, `dropped_by_retention`, `not_included`, `not_projected`, `not_requested`, `unavailable`, or `withheld` |

`delivered` means the final request contains the screenshot asset. An image
evicted by the configured retention policy gets a `dropped_by_retention` span
with the same screenshot ID, even if it was delivered previously.
`not_included` means the projected image did not reach the final request.
`not_projected` covers direct captures and projection hooks that bypass image
projection. `withheld` covers captures suppressed by secret redaction.

| `browserrig.operation` attribute | Value |
| --- | --- |
| `browserrig.action.id`, `browserrig.action.kind` | ID and kind shared with Browserrig action events |
| `browserrig.tool.name`, `browserrig.tool.call_id` | Tool name and Harnessed call ID. Explicit operations outside a tool use the action kind as the name |
| `browserrig.tab_id`, `browserrig.document_id` | Addressed page before the action |
| `browserrig.observation.id` | Current snapshot when the action began |
| `browserrig.screenshot.id`, `browserrig.screenshot.asset_id` | Latest screenshot visible to the model when the action began, including a retained screenshot |
| `browserrig.input.space` | `screenshot` for image pixels or `viewport` for CSS pixels |
| `browserrig.input.x`, `browserrig.input.y` | Coordinates supplied to a point tool, including rejected input |
| `browserrig.input.start.x`, `browserrig.input.start.y`, `browserrig.input.end.x`, `browserrig.input.end.y` | Coordinates supplied to a drag tool |
| `browserrig.viewport.x`, `browserrig.viewport.y`, `browserrig.viewport.start.*`, `browserrig.viewport.end.*` | Mapped or resolved pointer coordinates in viewport CSS pixels |
| `browserrig.target.ref`, `browserrig.target.source_ref`, `browserrig.target.target_ref`, `browserrig.target.target_id` | Supplied element references or target tab identifier |
| `browserrig.action.outcome` | `dispatched`, `blocked`, `failed`, or `cancelled` |
| `browserrig.action.started`, `browserrig.action.reason` | Whether the action reached its start boundary and why dispatch was blocked, failed, or cancelled |
| `browserrig.receipt.*` | Application-defined scalar attributes |

The operation span covers checks, dispatch and follow-up. A `dispatched` action
may still need a new observation to verify its effect on the page.

### Add receipt attributes from a plugin

Call `Actions.record_receipt` from `CheckAction` before dispatch or from
`ActionFinishedEvent` and `ActionFailedEvent` handlers to record the result.
Staging hooks and managed tool implementations can use the same method. It writes
to the enclosing operation span even when hook tracing adds a nested span. In an
`@hook(ActionFinishedEvent)` handler with an injected `Actions` service, call
`actions.record_receipt(hotspot_hit=matched)` to write
`browserrig.receipt.hotspot_hit`. Use booleans, numbers or strings. Calls outside
a managed action have no effect.

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
Explicit diagnostic attributes, including Browserrig URLs, action reasons and
extension receipts, are outside Harnessed's content filter. Browserrig applies
its `Secrets` redaction to captured URLs, action reasons and receipt strings.

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
