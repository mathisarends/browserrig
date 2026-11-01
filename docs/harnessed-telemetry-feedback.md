# Harnessed telemetry integration feedback

Collected while integrating **Harnessed 0.6.0** with Browserrig and **Phoenix
21.0.0** on Windows/Docker Desktop, 2026-10-30. These are local integration notes
for upstream discussion; no issue has been submitted.

## Integration effort and abstraction fit

The existing `plugins=[OpenTelemetryTracer(tracer_provider=provider)]` interface
fits Browserrig's composition without changing `browserrig.Agent` or any browser
plugin. A forwarding `otel` dependency extra, application startup/cleanup code
and a single-container Phoenix setup are sufficient. The integration adds no
Browserrig-specific tracing API.

Keeping provider ownership in the application is the right boundary: exporters,
credentials, resources, batching and shutdown can be shared with a backend's
existing telemetry. Lazy optional imports preserve Browserrig's provider-free
base installation. OpenInference kinds let Phoenix recognize agent, model and
tool spans without a Phoenix Python dependency in the application.

The main setup effort is standard OTel plumbing rather than agent composition.
The versioned Harnessed guide describes the provider lifecycle and standard
environment variables clearly. A complete local Docker recipe and a scripted
smoke test are useful additions for someone trying the integration for the
first time.

## Findings and suggested improvements

| Priority | Finding | Suggested upstream change |
| --- | --- | --- |
| High | The root `harnessed.turn` span has outcome and IDs but no captured input/output. Phoenix's trace overview cannot immediately show the user's task and final answer; users must open child model spans. Confirmed in the ingested smoke trace. | Populate bounded, opt-in turn-level input/output summaries with the same capture policy as child spans. Preserve distinct stopped/failed/partial results. |
| High | Captured model input serializes `ModelRequest.messages`, including system instructions and browser observations, but omits tool definitions, general model settings and output schema. This limits diagnosing what the model was actually offered. Confirmed by inspecting `OpenTelemetryTracer` in the installed 0.6.0 package. | Expose tool definitions and relevant resolved settings under documented, bounded attributes; document which request fields are intentionally excluded. |
| High | Content capture offers an on/off switch and a character limit but no integration-level redaction callback. Browserrig can redact its own observations, but arbitrary prompts, tool results and exception messages need an application policy. | Consider a synchronous, per-field sanitization/filter hook before serialization and size limiting. Keep metadata-only capture as the default. |
| Medium | Input/output is exported as generic JSON strings; truncation slices serialized JSON and changes the MIME type to text/plain. Large DOM observations or images can consume the budget and cut off later conversation entries. | Consider message-aware truncation, omitted-content counts and original lengths, while preserving a valid structured representation where practical. |
| Medium | The first live export received HTTP 401 while the scripted agent still completed successfully. The OTel SDK logged the failure; agent success is independent of export success. This was Phoenix 21's new auth default, resolved in the local Compose configuration. | Keep fail-open behavior; add an optional exporter health/diagnostic recipe to the getting-started guide. Do not claim successful delivery merely after shutdown/flush. |
| Medium | Runtime spans cover turns, steps, models and tools. Browser launch/readiness, observation work, CDP operations and browser events do not gain their own spans automatically. | Document how a downstream plugin can create correlated spans/events through a stable public API, including dependency and lifecycle semantics. Keep high-volume browser tracing opt-in. |

## Evidence and scope

`tests/test_telemetry.py` exercises an actual local OTLP/HTTP protobuf receiver.
It checks turn/step/model/tool parenting, session correlation, metadata-only
capture, model and tool inputs/outputs, per-field truncation and batch delivery
when the application exits through an exception. A subprocess test confirms
disabled tracing imports no OTel modules.

`examples/tracing_smoke.py` runs a real `browserrig.Agent` with headless Chrome and a
scripted model, then sends its spans to the Docker-hosted Phoenix instance. The
Phoenix `/v1/projects/browserrig/spans` endpoint permits checking persisted spans
and their attributes independently of the exporter log. The smoke test checks
that the navigation tool completed successfully.

Production concurrency, tail sampling, remote authenticated backends, SDK
transport instrumentation and large screenshot rendering are outside this
integration's verification scope. Provider usage/cost accuracy requires a live
model run; the scripted smoke test reports zero usage.

## Upstream references

- [Harnessed 0.6.0 tracing guide](https://github.com/mathisarends/harnessed/blob/v0.6.0/docs/guides/tracing.md)
- [Harnessed tracer implementation](https://github.com/mathisarends/harnessed/blob/v0.6.0/harnessed/integrations/opentelemetry.py)
- [Phoenix 21 auth default change](https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v21.0.0)
- [Browserrig setup and commands](telemetry.md)
