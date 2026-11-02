"""Application-owned OTel setup shared by the runnable examples.

Agent accepts Harnessed's tracer directly through plugins; no Browserrig
tracer or global provider is needed. Imports stay lazy for runs without --trace.
"""

from __future__ import annotations

# Optional imports intentionally happen only when tracing is enabled.
# pylint: disable=import-outside-toplevel
import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from harnessed.kernel import PluginLike

if TYPE_CHECKING:
    from harnessed.integrations.opentelemetry import ContentCapture, TraceContentFilter


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
    capture_content: bool | ContentCapture = False,
    max_content_length: int = 16_384,
    content_filter: TraceContentFilter | None = None,
) -> AsyncIterator[list[PluginLike]]:
    if not enabled and not capture_content:
        yield []
        return

    # Optional dependencies belong to application startup, never Browserrig imports.
    try:
        from harnessed.integrations.opentelemetry import (
            OpenTelemetryTracer,
            otlp_provider,
        )
    except ImportError as error:
        raise RuntimeError(
            "Tracing requires the otel extra: uv sync --extra otel"
        ) from error

    # Standard OTLP variables stay in charge; without them, export to local Phoenix.
    configured = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    # The provider flushes its batch on exit, after sessions closed, including on errors.
    async with otlp_provider(
        service_name=os.getenv("OTEL_SERVICE_NAME", "browserrig"),
        endpoint=None if configured else "http://127.0.0.1:6006/v1/traces",
        resource_attributes={
            "openinference.project.name": os.getenv(
                "PHOENIX_PROJECT_NAME", "browserrig"
            )
        },
    ) as provider:
        yield [
            OpenTelemetryTracer(
                tracer_provider=provider,
                capture_content=capture_content,
                max_content_length=max_content_length,
                content_filter=content_filter,
            )
        ]
