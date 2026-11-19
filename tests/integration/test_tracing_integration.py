import base64
import hashlib

import pytest
from harnessed import Plugin, PolicyDecision, ToolCall, hook
from harnessed.kernel import needs
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel, call

from browserrig import (
    Actions,
    Agent,
    Chrome,
    CursorMarker,
    Screenshots,
    ScreenshotTrigger,
    Viewport,
)
from browserrig.core import ActionKind, BrowserError
from browserrig.events import ActionFinishedEvent
from browserrig.tools import CheckAction
from tests.observations import latest

pytestmark = pytest.mark.integration


@pytest.fixture(name="trace_provider")
def in_memory_trace_provider():
    pytest.importorskip("opentelemetry.sdk.trace")
    # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


@pytest.mark.parametrize("trace_hooks", [False, True])
async def test_browser_methods_nest_below_harnessed_spans(
    site, trace_hooks, trace_provider
):
    # pylint: disable=import-outside-toplevel
    from harnessed.integrations.opentelemetry import OpenTelemetryTracer

    provider, exporter = trace_provider
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
        browser=Chrome.launch(url=site),
        plugins=[
            Approvals(default=PolicyDecision.ALLOW),
            OpenTelemetryTracer(tracer_provider=provider, trace_hooks=trace_hooks),
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
        return [span for span in spans if span.name == name]

    captures = named("browserrig.observation")
    assert captures and all("harnessed.step" in ancestors(s) for s in captures)
    (click,) = [
        span
        for span in named("browserrig.tools.execution.transaction.ActionRunner.run")
        if span.attributes["harnessed.kind"] == "click"
    ]
    assert "harnessed.tool" in ancestors(click)
    waits = named("browserrig.readiness.wait.wait_for_page")
    assert waits and all(
        "harnessed.status" in span.attributes and "harnessed.polls" in span.attributes
        for span in waits
    )
    settle = named("browserrig.tools.execution.dispatch.ActionDispatch._settle")[0]
    assert (
        settle.attributes["code.file.path"]
        .replace("\\", "/")
        .endswith("browserrig/tools/execution/dispatch.py")
    )
    assert isinstance(settle.attributes["code.line.number"], int)
    expected = {
        "browserrig.dom.extraction.extract",
        "browserrig.dom.extraction.accessibility.chrome_names",
        "browserrig.browser.tab.Tab.frames",
        "browserrig.input.mouse.Mouse.click",
        "browserrig.operation",
        "browserrig.core.BrowserCoordination.acquire",
    }
    assert expected <= {span.name for span in spans}
    (operation,) = named("browserrig.operation")
    assert operation.attributes["browserrig.tool.name"] == "click"
    assert operation.attributes["browserrig.target.ref"]
    assert operation.attributes["browserrig.action.outcome"] == "dispatched"
    hooks = named("harnessed.hook")
    assert bool(hooks) is trace_hooks
    if trace_hooks:
        assert "harnessed.hook" in ancestors(click)
        assert all("code.function.name" in span.attributes for span in hooks)


async def test_screenshot_assets_link_to_actions_and_model_spans(site, trace_provider):
    # pylint: disable=import-outside-toplevel
    from harnessed.integrations.opentelemetry import OpenTelemetryTracer

    provider, exporter = trace_provider
    agent = Agent(
        model=ScriptedModel(
            [
                call(
                    "screenshot", region={"x": 20, "y": 20, "width": 160, "height": 80}
                ),
                call("click_at", x=12, y=14),
                call("drag_at", start={"x": 5, "y": 6}, end={"x": 20, "y": 40}),
                call("move_mouse", x=9999, y=0),
                "Done",
            ]
        ),
        browser=Chrome.launch(url=site + "/gestures", viewport=Viewport(scale=2)),
        plugins=[
            Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            CursorMarker(),
            Approvals(default=PolicyDecision.ALLOW),
            _HotspotReceipt(),
            OpenTelemetryTracer(
                tracer_provider=provider, capture_content=True, trace_hooks=True
            ),
        ],
    )
    result = await agent.run("Click the button in the cropped screenshot.")
    assert result.text == "Done"

    spans = exporter.get_finished_spans()
    observations = [
        span.attributes for span in spans if span.name == "browserrig.observation"
    ]
    outcomes = {attrs["browserrig.observation.outcome"] for attrs in observations}
    assert outcomes == {"delivered", "skipped_unchanged", "dropped_by_retention"}
    operations = {
        span.attributes["browserrig.tool.name"]: span.attributes
        for span in spans
        if span.name == "browserrig.operation"
    }
    click = operations["click_at"]
    screenshot_id = click["browserrig.screenshot.id"]
    (delivered,) = [
        attrs
        for attrs in observations
        if attrs["browserrig.screenshot.id"] == screenshot_id
        and attrs["browserrig.observation.outcome"] == "delivered"
    ]
    assert delivered["browserrig.screenshot.width"] == 160
    assert delivered["browserrig.screenshot.height"] == 80
    assert delivered["browserrig.screenshot.device_scale"] == 2
    assert delivered["browserrig.url"] == site + "/gestures"
    assert delivered["browserrig.tab_id"] == click["browserrig.tab_id"]
    assert delivered["browserrig.document_id"] == click["browserrig.document_id"]
    assert (
        click["browserrig.screenshot.asset_id"]
        == delivered["browserrig.screenshot.asset_id"]
    )
    assert click["browserrig.input.space"] == "screenshot"
    assert (click["browserrig.input.x"], click["browserrig.input.y"]) == (12, 14)
    assert (click["browserrig.viewport.x"], click["browserrig.viewport.y"]) == (32, 34)
    assert click["browserrig.action.outcome"] == "dispatched"
    assert click["browserrig.receipt.hotspot_hit"] is True
    assert not any("image.image.url" in key for key in click)

    images = {
        _image_digest(value): span.attributes["harnessed.request_id"]
        for span in spans
        if span.name == "harnessed.model"
        for key, value in span.attributes.items()
        if key.endswith(".image.image.url")
    }
    assert (
        images[click["browserrig.screenshot.asset_id"]]
        == delivered["browserrig.request.id"]
    )
    blocked = operations["drag_at"]
    assert blocked["browserrig.action.outcome"] == "blocked"
    assert blocked["browserrig.action.reason"] == "Hotspot does not accept drag"
    assert blocked["browserrig.action.started"] is False
    assert blocked["browserrig.screenshot.asset_id"] in images
    assert blocked["browserrig.input.start.x"] == 5
    assert blocked["browserrig.input.end.y"] == 40
    failed = operations["move_mouse"]
    assert failed["browserrig.action.outcome"] == "failed"
    assert "outside" in failed["browserrig.action.reason"]
    assert failed["browserrig.screenshot.id"] == blocked["browserrig.screenshot.id"]
    assert any(
        attrs.get("browserrig.screenshot.reused_id")
        == failed["browserrig.screenshot.id"]
        for attrs in observations
    )


class _HotspotReceipt(Plugin):
    _actions = needs(Actions)

    @hook(CheckAction)
    def check(self, action: CheckAction) -> None:
        if action.kind is ActionKind.DRAG_AT:
            raise BrowserError("Hotspot does not accept drag")

    @hook(ActionFinishedEvent)
    def receipt(self, action: ActionFinishedEvent) -> None:
        if action.kind is ActionKind.CLICK_AT:
            self._actions.record_receipt(hotspot_hit=True)


def _image_digest(data_url: str) -> str:
    return hashlib.sha256(base64.b64decode(data_url.partition(",")[2])).hexdigest()
