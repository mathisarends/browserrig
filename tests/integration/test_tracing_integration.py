import pytest
from harnessed import Agent, PolicyDecision, ToolCall
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Chrome, browser_plugins
from tests.observations import latest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("trace_hooks", [False, True])
async def test_browser_methods_nest_below_harnessed_spans(site, trace_hooks):
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
            OpenTelemetryTracer(tracer_provider=provider, trace_hooks=trace_hooks),
        ],
    )
    result = await agent.run("Submit the form.")
    provider.shutdown()
    assert result.text == "Done"

    spans = exporter.get_finished_spans()
    by_id = {span.context.span_id: span for span in spans}

    def ancestors(span):
        while span.parent is not None and span.parent.span_id in by_id:
            span = by_id[span.parent.span_id]
            yield span.name

    def named(name):
        return [span for span in spans if span.name == name]

    captures = named("browserrig.observation.plugin.BrowserPerception.capture")
    assert captures and all("harnessed.step" in ancestors(s) for s in captures)
    (click,) = [
        span
        for span in named("browserrig.tools.execution.Actions.run")
        if span.attributes["harnessed.kind"] == "click"
    ]
    assert "harnessed.tool" in ancestors(click)
    waits = named("browserrig.readiness.wait.wait_for_page")
    assert waits and all(
        "harnessed.status" in span.attributes and "harnessed.polls" in span.attributes
        for span in waits
    )
    settle = named("browserrig.tools.execution.Actions._settle")[0]
    assert (
        settle.attributes["code.file.path"]
        .replace("\\", "/")
        .endswith("browserrig/tools/execution.py")
    )
    assert isinstance(settle.attributes["code.line.number"], int)
    for name in (
        "browserrig.observation.extraction.extract",
        "browserrig.observation.extraction.accessibility.chrome_names",
        "browserrig.browser.tab.Tab.frames",
        "browserrig.input.mouse.Mouse.click",
        "browserrig.operation",
    ):
        assert named(name), name
    hooks = named("harnessed.hook")
    assert bool(hooks) is trace_hooks
    if trace_hooks:
        assert "harnessed.hook" in ancestors(click)
        assert all("code.function.name" in span.attributes for span in hooks)
