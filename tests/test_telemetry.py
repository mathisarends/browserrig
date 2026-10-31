import asyncio
import subprocess
import sys

import pytest
from harnessed import Agent, Plugin, PolicyDecision, tool
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from examples.telemetry import tracing_plugins


def test_disabled_tracing_keeps_optional_dependencies_unloaded():
    script = """
import asyncio
import sys
from examples.telemetry import tracing_plugins

async def main():
    async with tracing_plugins() as plugins:
        assert plugins == []
    assert not any(name.startswith('opentelemetry') for name in sys.modules)

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(name="collector")
async def otlp_collector(monkeypatch):
    pytest.importorskip("opentelemetry.sdk.trace")
    trace_service = pytest.importorskip(
        "opentelemetry.proto.collector.trace.v1.trace_service_pb2"
    )

    requests = []

    async def receive(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode().split("\r\n")
            length = next(
                int(line.split(":", 1)[1])
                for line in lines
                if line.lower().startswith("content-length:")
            )
            body = await reader.readexactly(length)
            requests.append(
                (lines[0], trace_service.ExportTraceServiceRequest.FromString(body))
            )
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", f"http://127.0.0.1:{port}/v1/traces"
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_COMPRESSION", "none")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "browserrig-test")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "browserrig-test")
    try:
        yield requests
    finally:
        server.close()
        await server.wait_closed()


class Echo(Plugin):
    @tool(readonly=True)
    async def echo(self, value: str) -> str:
        """Return the supplied value."""
        return value


def _attributes(attributes):
    return {
        item.key: getattr(item.value, item.value.WhichOneof("value"))
        for item in attributes
    }


@pytest.mark.parametrize("capture_content", [False, True])
async def test_otlp_export_contains_correlated_model_and_tool_spans(
    collector, capture_content
):
    async with tracing_plugins(
        enabled=True, capture_content=capture_content
    ) as plugins:
        agent = Agent(
            model=ScriptedModel([call("echo", value="TOOL INPUT"), "MODEL OUTPUT"]),
            plugins=[*plugins, Echo(), Approvals(default=PolicyDecision.ALLOW)],
        )
        async with agent.session() as session:
            result = await session.run("MODEL INPUT")
            assert result.text == "MODEL OUTPUT"
            session_id = session.id

    assert collector and all(
        path == "POST /v1/traces HTTP/1.1" for path, _ in collector
    )
    resources = [
        resource for _, request in collector for resource in request.resource_spans
    ]
    assert all(
        _attributes(r.resource.attributes)["service.name"] == "browserrig-test"
        for r in resources
    )
    spans = [span for r in resources for scope in r.scope_spans for span in scope.spans]
    turn = next(span for span in spans if span.name == "harnessed.turn")
    steps = [span for span in spans if span.name == "harnessed.step"]
    models = [span for span in spans if span.name == "harnessed.model"]
    tool_span = next(span for span in spans if span.name == "harnessed.tool")
    assert len(steps) == len(models) == 2
    assert all(span.trace_id == turn.trace_id for span in spans)
    assert all(span.parent_span_id == turn.span_id for span in steps)
    assert all(
        span.parent_span_id in {step.span_id for step in steps} for span in models
    )
    assert tool_span.parent_span_id in {step.span_id for step in steps}
    assert _attributes(tool_span.attributes)["tool.name"] == "echo"
    assert all(
        _attributes(span.attributes)["session.id"] == session_id for span in spans
    )
    contents = str([_attributes(span.attributes) for span in spans])
    for content in ("MODEL INPUT", "MODEL OUTPUT", "TOOL INPUT"):
        assert (content in contents) is capture_content
    if capture_content:
        assert "TOOL INPUT" in _attributes(tool_span.attributes)["input.value"]
        assert "TOOL INPUT" in _attributes(tool_span.attributes)["output.value"]


async def test_content_is_bounded_and_batches_flush_when_host_fails(collector):
    with pytest.raises(RuntimeError, match="host failed"):
        async with tracing_plugins(
            capture_content=True, max_content_length=20
        ) as plugins:
            result = await Agent(model=ScriptedModel(["x" * 100]), plugins=plugins).run(
                "y" * 100
            )
            assert result.text == "x" * 100
            raise RuntimeError("host failed")
    spans = [
        span
        for _, request in collector
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    model = _attributes(
        next(span for span in spans if span.name == "harnessed.model").attributes
    )
    for direction in ("input", "output"):
        assert len(model[f"{direction}.value"]) == 20
        assert model[f"harnessed.{direction}.truncated"] is True
        assert model[f"{direction}.mime_type"] == "text/plain"
