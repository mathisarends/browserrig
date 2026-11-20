"""Session-owned tracing for eval attempts."""

import os

from harnessed import Plugin

DEFAULT_PROJECT = "browserrig-evals"


def tracing_plugins(enabled: bool, project: str) -> tuple[Plugin, ...]:
    if not enabled:
        return ()

    # Large browser observations produce sizeable spans. Keep batches small and
    # allow a busy local collector enough time; explicit user settings still win.
    os.environ.setdefault("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "32")
    os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "1000")
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "60")

    # OTel is an optional extra.
    # pylint: disable=import-outside-toplevel
    from harnessed.integrations.opentelemetry import OTLPTracing

    configured = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    return (
        OTLPTracing(
            service_name=os.getenv("OTEL_SERVICE_NAME", "browserrig"),
            endpoint=None if configured else "http://127.0.0.1:6006/v1/traces",
            resource_attributes={"openinference.project.name": project},
            capture_content=True,
            max_content_length=400_000,
        ),
    )
