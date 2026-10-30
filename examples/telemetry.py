"""Application-owned OTel setup shared by the runnable examples.

BrowserAgent accepts Harnessed's tracer directly through plugins; no Browserrig
tracer or global provider is needed. Imports stay lazy for runs without --trace.
"""

# Optional imports intentionally happen only when tracing is enabled.
# pylint: disable=import-outside-toplevel

import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from harnessed.kernel import PluginLike


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def add_tracing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trace", action="store_true", help="Export agent traces to local Phoenix/OTLP"
    )
    parser.add_argument(
        "--trace-content",
        action="store_true",
        help="Also capture model/tool inputs and outputs (implies --trace; may contain secrets)",
    )
    parser.add_argument(
        "--trace-max-content-length",
        type=_positive_int,
        default=16_384,
        help="Maximum characters per captured input/output field (default: 16384)",
    )


@asynccontextmanager
async def tracing_plugins(
    *,
    enabled: bool = False,
    capture_content: bool = False,
    max_content_length: int = 16_384,
) -> AsyncIterator[list[PluginLike]]:
    if not enabled and not capture_content:
        yield []
        return

    # Optional dependencies belong to application startup, never Browserrig imports.
    try:
        from harnessed.integrations.opentelemetry import OpenTelemetryTracer
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as error:
        raise RuntimeError("Tracing requires the otel extra: uv sync --extra otel") from error

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "browserrig"),
                "openinference.project.name": os.getenv("PHOENIX_PROJECT_NAME", "browserrig"),
            }
        )
    )
    try:
        # Standard endpoint/header/timeout variables remain exporter-owned. Only
        # supply a local default when neither standard endpoint is configured.
        exporter = (
            OTLPSpanExporter()
            if os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            else OTLPSpanExporter(endpoint="http://127.0.0.1:6006/v1/traces")
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        yield [
            OpenTelemetryTracer(
                tracer_provider=provider,
                capture_content=capture_content,
                max_content_length=max_content_length,
            )
        ]
    finally:
        # Close sessions first; flush the batch outside the event loop, including
        # on errors. Never replace or shut down a host's global provider.
        await asyncio.to_thread(provider.shutdown)
