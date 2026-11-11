import asyncio
import json
import subprocess
import sys
from dataclasses import replace

import pytest
from harnessed import Agent, Plugin, PolicyDecision, tool
from harnessed.kernel import needs
from harnessed.models import ModelInfo
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call
from pydantic import BaseModel

from browserrig import Files, FileSystem, LocalWorkspace, TaskMemory, WorkspaceTools
from examples.telemetry import tracing_plugins


async def test_memory_handover_exports_correlated_metadata_without_note_contents(
    collector, tmp_path
):
    notes = "PRIVATE MEMORY TEXT: candidate 42, purchase unconfirmed."
    summary = ScriptedModel(["Earlier work summarized."])
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            call("write_file", path="more.txt", content="more " * 4000),
            call("write_file", path="notes/task_state.md", content=notes),
            call("read_file", path="notes/task_state.md"),
            "Finished",
        ],
        info=ModelInfo("test"),
    )
    async with tracing_plugins(enabled=True, capture_content=False) as tracing:
        await Agent(
            model=model,
            plugins=[
                *tracing,
                Files(LocalWorkspace(tmp_path)),
                WorkspaceTools(),
                TaskMemory(
                    trigger=lambda state: state.input_tokens >= 5000,
                    fallback_tokens=5000,
                    llm=summary,
                    keep_last_steps=1,
                ),
                Approvals(default=PolicyDecision.ALLOW),
            ],
        ).run("Compare products", max_steps=8)
    spans = [
        span
        for _, request in collector
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    receipts = [
        _attributes(span.attributes)
        for span in spans
        if span.name == "browserrig.memory"
    ]
    compacted = next(r for r in receipts if r["harnessed.action"] == "compacted")
    restored = next(r for r in receipts if r["harnessed.action"] == "restored")
    assert compacted["harnessed.checkpoint_saved"] is True
    assert compacted["harnessed.compaction_id"] == restored["harnessed.compaction_id"]
    assert compacted["harnessed.revision"] == restored["harnessed.revision"]
    assert restored["harnessed.restore_pending"] is False
    assert any(span.name == "browserrig.memory.defer_compaction" for span in spans)
    assert len(summary.requests) == 1
    assert notes not in str(spans)


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


class FileEcho(Plugin):
    files = needs(FileSystem)

    @tool(readonly=True)
    async def file_echo(self) -> str:
        """Read the test note."""
        return (await self.files.read_file("note.txt")).text


class TraceAnswer(BaseModel):
    value: str


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
        turn_attributes = _attributes(turn.attributes)
        assert "MODEL INPUT" in turn_attributes["input.value"]
        assert "MODEL OUTPUT" in turn_attributes["output.value"]
        for model in models:
            attributes = _attributes(model.attributes)
            assert "echo" in attributes["request.tools.value"]
            assert isinstance(json.loads(attributes["request.settings.value"]), dict)
        assert "TOOL INPUT" in _attributes(tool_span.attributes)["input.value"]
        assert "TOOL INPUT" in _attributes(tool_span.attributes)["output.value"]


@pytest.mark.parametrize("direction", ["input", "output"])
async def test_content_is_bounded_and_batches_flush_when_host_fails(
    collector, direction
):
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
    assert len(model[f"{direction}.value"]) <= 20
    json.loads(model[f"{direction}.value"])
    assert model[f"harnessed.{direction}.truncated"] is True
    assert model[f"{direction}.mime_type"] == "application/json"


async def test_redaction_and_application_filter_leave_live_history_intact(collector):
    from harnessed.integrations.opentelemetry import (  # pylint: disable=import-outside-toplevel
        ContentCapture,
        TraceContentKind,
    )
    from pydantic import SecretStr  # pylint: disable=import-outside-toplevel

    secret = "credential-12345"
    seen = []

    def filter_content(content):
        seen.append(content.kind)
        if content.kind is TraceContentKind.TOOL_RESULT:
            return None
        if content.kind is TraceContentKind.TOOL_ARGUMENTS:
            return replace(content, value={"replacement": secret})
        return content

    model = ScriptedModel([call("echo", value=secret), f"Answer: {secret}"])
    async with tracing_plugins(
        capture_content=ContentCapture.redacted(SecretStr(secret)),
        content_filter=filter_content,
    ) as plugins:
        result = await Agent(
            model=model,
            plugins=[*plugins, Echo(), Approvals(default=PolicyDecision.ALLOW)],
        ).run(f"Input: {secret}")
    assert result.text == f"Answer: {secret}"
    assert any(secret in str(message) for message in model.requests[-1].messages)
    spans = [
        span
        for _, request in collector
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    assert spans and secret not in str(spans)
    tool_attributes = _attributes(
        next(span for span in spans if span.name == "harnessed.tool").attributes
    )
    assert "replacement" in tool_attributes["input.value"]
    assert "[redacted]" in tool_attributes["input.value"]
    assert "output.value" not in tool_attributes
    assert TraceContentKind.MODEL_INPUT in seen
    assert TraceContentKind.MODEL_OUTPUT in seen

    assert TraceContentKind.TURN_INPUT in seen
    assert TraceContentKind.TURN_OUTPUT in seen
    assert TraceContentKind.MODEL_TOOLS in seen
    assert TraceContentKind.MODEL_SETTINGS in seen


@pytest.mark.parametrize("trace_hooks", [False, True])
async def test_library_and_worker_spans_share_the_tool_context(
    collector, tmp_path, trace_hooks
):
    (tmp_path / "note.txt").write_text("PRIVATE FILE CONTENT", encoding="utf-8")
    async with tracing_plugins(
        enabled=not trace_hooks, trace_hooks=trace_hooks
    ) as plugins:
        result = await Agent(
            model=ScriptedModel([call("file_echo"), "Read"]),
            plugins=[
                *plugins,
                Files(LocalWorkspace(tmp_path)),
                FileEcho(),
                Approvals(default=PolicyDecision.ALLOW),
            ],
        ).run("Read the note")
    assert result.text == "Read"
    spans = [
        span
        for _, request in collector
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    tool_span = next(span for span in spans if span.name == "harnessed.tool")
    read = next(
        span
        for span in spans
        if span.name == "browserrig.files.system.FileSystem.read_file"
    )
    worker = next(
        span
        for span in spans
        if span.name == "browserrig.files.reading.FileReader.read"
    )
    assert read.parent_span_id == tool_span.span_id
    assert worker.parent_span_id == read.span_id
    assert worker.trace_id == read.trace_id == tool_span.trace_id
    assert _attributes(worker.attributes)["harnessed.format"] == "text"
    hooks = [span for span in spans if span.name == "harnessed.hook"]
    assert bool(hooks) is trace_hooks
    if trace_hooks:
        assert any(span.trace_id == tool_span.trace_id for span in hooks)
        assert all("harnessed.hook.event" in _attributes(s.attributes) for s in hooks)
    assert "PRIVATE FILE CONTENT" not in str(spans)


async def test_structured_turn_output_and_schema_use_the_content_policy(collector):
    from harnessed.integrations.opentelemetry import (  # pylint: disable=import-outside-toplevel
        ContentCapture,
        TraceContentKind,
    )

    secret = "structured-secret-123"
    seen = []

    def filter_content(content):
        seen.append(content.kind)
        return content

    async with tracing_plugins(
        capture_content=ContentCapture.redacted(secret), content_filter=filter_content
    ) as plugins:
        result = await Agent(
            model=ScriptedModel(
                [json.dumps({"value": secret})],
                info=ModelInfo("test", supports_structured_output=True),
            ),
            plugins=plugins,
        ).run("Return the value", output=TraceAnswer)
    assert result.output == TraceAnswer(value=secret)
    spans = [
        span
        for _, request in collector
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    turn = _attributes(next(s for s in spans if s.name == "harnessed.turn").attributes)
    output = json.loads(turn["output.value"])
    assert output["validated_output"] == {"value": "[redacted]"}
    model = _attributes(
        next(s for s in spans if s.name == "harnessed.model").attributes
    )
    assert "TraceAnswer" in model["request.output_schema.value"]
    assert TraceContentKind.MODEL_OUTPUT_SCHEMA in seen
    assert TraceContentKind.TURN_OUTPUT in seen
    assert secret not in str(spans)
