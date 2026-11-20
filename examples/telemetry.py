"""Session-owned OTel setup shared by the runnable examples."""

from __future__ import annotations

# Optional imports intentionally happen only when tracing is enabled.
# pylint: disable=import-outside-toplevel
import argparse
import os
from typing import TYPE_CHECKING

from harnessed import Plugin

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
        "--trace-hooks",
        action="store_true",
        help="Trace each hook invocation to find harness overhead (implies --trace)",
    )
    parser.add_argument(
        "--trace-content",
        action="store_true",
        help=(
            "Also capture turn/model/tool content and request details "
            "(implies --trace; may contain secrets)"
        ),
    )
    parser.add_argument(
        "--trace-max-content-length",
        type=_positive_int,
        default=16_384,
        help="Character limit for captured fields and model message parts (default: 16384)",
    )


def tracing_plugins(
    *,
    enabled: bool = False,
    capture_content: bool | ContentCapture = False,
    trace_hooks: bool = False,
    max_content_length: int = 16_384,
    content_filter: TraceContentFilter | None = None,
) -> list[Plugin]:
    if not enabled and not capture_content and not trace_hooks:
        return []

    try:
        from harnessed.integrations.opentelemetry import OTLPTracing
    except ImportError as error:
        raise RuntimeError(
            "Tracing requires the otel extra: uv sync --extra otel"
        ) from error

    # Standard OTLP variables stay in charge; without them, export to local Phoenix.
    configured = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    return [
        OTLPTracing(
            service_name=os.getenv("OTEL_SERVICE_NAME", "browserrig"),
            endpoint=None if configured else "http://127.0.0.1:6006/v1/traces",
            resource_attributes={
                "openinference.project.name": os.getenv(
                    "PHOENIX_PROJECT_NAME", "browserrig"
                )
            },
            capture_content=capture_content,
            max_content_length=max_content_length,
            content_filter=content_filter,
            trace_hooks=trace_hooks,
        )
    ]
