"""Application-owned tracing setup; optional OTel imports stay lazy."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from harnessed.kernel import PluginLike

DEFAULT_PROJECT = "browserrig-evals"


@asynccontextmanager
async def tracing_plugins(
    enabled: bool, project: str
) -> AsyncGenerator[tuple[PluginLike, ...]]:
    if not enabled:
        yield ()
        return

    # Large browser observations produce sizeable spans. Keep batches small and
    # allow a busy local collector enough time; explicit user settings still win.
    os.environ.setdefault("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "32")
    os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "1000")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "60")

    # OTel is an optional extra.
    # pylint: disable=import-outside-toplevel
    from harnessed.integrations.opentelemetry import OpenTelemetryTracer, otlp_provider

    configured = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    async with otlp_provider(
        service_name=os.getenv("OTEL_SERVICE_NAME", "browserrig"),
        endpoint=None if configured else "http://127.0.0.1:6006/v1/traces",
        resource_attributes={"openinference.project.name": project},
    ) as provider:
        yield (
            OpenTelemetryTracer(
                tracer_provider=provider,
                capture_content=True,
                max_content_length=400_000,
            ),
        )
