import pytest
from harnessed import Agent, PolicyDecision, ToolCall
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Chrome, browser_plugins
from tests.observations import latest

pytestmark = pytest.mark.integration


async def test_browser_methods_nest_below_harnessed_spans(site):
    pytest.importorskip("opentelemetry.sdk.trace")
    # pylint: disable=import-outside-toplevel
    from harnessed.integrations.opentelemetry import OpenTelemetryTracer
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    steps = 0

    async def respond(request):
        nonlocal steps
        steps += 1
        if steps == 1:
            refs = {e["name"]: e["ref"] for e in latest(request.messages)["elements"]}
            yield ModelChunk(tool_call=ToolCall("click", {"ref": refs["Submit"]}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            *browser_plugins(browser=Chrome.launch(url=site)),
            Approvals(default=PolicyDecision.ALLOW),
            OpenTelemetryTracer(tracer_provider=provider),
        ],
    )
    result = await agent.run("Submit the form.")
    assert result.text == "Done"

    spans = exporter.get_finished_spans()
    by_id = {span.context.span_id: span for span in spans}

    def ancestors(span):
        while span.parent is not None and span.parent.span_id in by_id:
            span = by_id[span.parent.span_id]
            yield span.name

    def named(name):
        return [span for span in spans if span.name == f"harnessed.{name}"]

    captures = named("BrowserPerception.capture")
    assert captures and all("harnessed.step" in ancestors(s) for s in captures)
    (click,) = [
        span
        for span in named("Actions.run")
        if span.attributes["harnessed.kind"] == "click"
    ]
    assert "harnessed.tool" in ancestors(click)
    waits = named("wait_for_page")
    assert waits and all(
        "harnessed.status" in span.attributes and "harnessed.polls" in span.attributes
        for span in waits
    )
    settle = named("Actions._settle")[0]
    assert (
        settle.attributes["harnessed.code.filepath"] == "browserrig/tools/execution.py"
    )
    assert isinstance(settle.attributes["harnessed.code.lineno"], int)
    for name in ("extract", "chrome_names", "Tab.frames", "Mouse.click", "operation"):
        assert named(name), name
