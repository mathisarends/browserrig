import asyncio
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, ToolCall
from harnessed.models import ImagePart, ModelChunk, ToolMessage
from harnessed.testing import ScriptedModel

from browserrig import (
    ActionKind,
    Actions,
    BrowserCoordination,
    BrowserPerception,
    CaptureContent,
    CaptureStrategy,
    DomRenderer,
    ElementInfo,
    MultiTab,
    PageContent,
    PageReadiness,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTools,
    SingleTab,
    TextObservations,
)
from browserrig.browser import OpenDialog, TabInfo
from browserrig.core import BrowserError, Region
from browserrig.observation import Snapshot
from browserrig.tools import Effect
from tests.fakes import FakeChrome

_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGhg"
    "AAAAASUVORK5CYII="
)


def test_metadata_text_defaults_to_lightweight_capture_and_renders_only_page_facts():
    perception = BrowserPerception(text=TextObservations(content="metadata"))
    snapshot = Snapshot(
        id="observation",
        tab_id="tab",
        document_id="document",
        url="https://example.org/shop",
        title="Shop",
        readiness="ready",
        width=1280,
        height=800,
        scroll_y=400,
        page_height=2000,
        fingerprint="fingerprint",
        elements=(ElementInfo(ref="1", role="button", name="Page control"),),
        text="Page prose",
        tabs=(
            TabInfo(
                id="tab", url="https://example.org/shop", title="Shop", active=True
            ),
        ),
    )

    assert isinstance(perception.capture_strategy, ScreenshotCapture)
    assert perception.renderer.refs() is None
    assert perception.renderer.render(snapshot).splitlines() == [
        "# Shop",
        "url: https://example.org/shop",
        "tab: tab",
        "open tabs: 1",
        "viewport: 1280x800, scroll y=400px, 800px remaining to page end",
        "cursor: not in this tab yet",
    ]


@pytest.mark.parametrize("content", ["metadata", "page"])
async def test_observation_reports_javascript_dialog_kind_and_message_once(content):
    holder = {}
    model = ScriptedModel(["Done"])
    agent = Agent(
        model=model,
        plugins=[
            FakeChrome(holder),
            PageReadiness(),
            BrowserPerception(text=TextObservations(content=content)),
        ],
    )
    async with agent.session() as session:
        holder["browser"].active_tab.dialog = OpenDialog("confirm", "Discard changes?")
        await session.run("Inspect the page")

    (observation,) = [
        message.text
        for message in model.requests[0].messages
        if "readiness: blocked" in message.text
    ]
    assert observation.count("Open confirm dialog: Discard changes?") == 1
    assert ("page text:" in observation) is (content == "page")


@pytest.mark.parametrize("mode, overview", [(SingleTab, False), (MultiTab, True)])
async def test_tab_overview_is_collected_only_for_multi_tab(mode, overview):
    holder = {}
    listed = (
        TabInfo(id="tab-1", url="https://example.org/", title="Example", active=True),
        TabInfo(id="other", url="https://private.example/", title="Other page"),
    )

    class PageCapture(CaptureStrategy):
        async def collect(self, tab, _report, **_options):
            return CaptureContent(
                page=PageContent(
                    url=tab.url,
                    title=tab.title,
                    width=800,
                    height=600,
                    scroll_y=0,
                    page_height=600,
                )
            )

    perception = BrowserPerception(capture=PageCapture(), renderer=DomRenderer())
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[FakeChrome(holder), mode(), PageReadiness(), perception],
    )
    async with agent.session() as session:
        list_tabs = AsyncMock(return_value=listed)
        holder["browser"].tabs.list = list_tabs
        active = session.scope[BrowserPerception]
        snapshot = await active.capture()
        probe = await active.probe(holder["browser"].active_tab)
        assert snapshot.tabs == probe.tabs == (listed if overview else ())
        assert snapshot.tab_id == probe.tab_id == "tab-1"
        rendered = active.project(snapshot).text
        assert ("tabs (* = this tab)" in rendered) is overview
        assert ("Other page" in rendered) is overview
        if overview:
            assert list_tabs.await_count == 2
        else:
            list_tabs.assert_not_awaited()


async def test_step_observation_and_actions_share_session_control():
    holder = {}
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingCapture(CaptureStrategy):
        async def collect(self, tab, _report, **_options):
            assert holder["coordination"].busy
            entered.set()
            await release.wait()
            return CaptureContent(
                page=PageContent(
                    url=tab.url,
                    title=tab.title,
                    width=800,
                    height=600,
                    scroll_y=0,
                    page_height=600,
                )
            )

    async def operate(_tab):
        assert holder["coordination"].busy
        return Effect("Executed once.")

    operation = AsyncMock(side_effect=operate)
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[
            FakeChrome(holder),
            PageReadiness(),
            BrowserPerception(capture=BlockingCapture(), renderer=DomRenderer()),
            Actions(),
        ],
    )
    async with agent.session() as session:
        assert session.scope[BrowserCoordination] is holder["coordination"]
        async with asyncio.timeout(10), asyncio.TaskGroup() as tasks:
            run = tasks.create_task(session.run("Observe"))
            await entered.wait()
            action = tasks.create_task(
                session.scope[Actions].run(
                    kind=ActionKind.NAVIGATE, operation=operation, settle=False
                )
            )
            await asyncio.sleep(0)
            operation.assert_not_awaited()
            release.set()
        assert run.result().text == "Done"
        assert action.result().text == "Executed once."
        operation.assert_awaited_once()
        assert not holder["coordination"].busy


@pytest.mark.parametrize("replace_region", [False, True])
async def test_screenshot_request_survives_a_failed_capture(replace_region):
    original = Region(x=2, y=3, width=8, height=8)
    attempts = []

    class FailingCapture(CaptureStrategy):
        async def collect(self, tab, _report, *, screenshots, region, **_options):
            attempts.append((screenshots, region))
            if len(attempts) == 1:
                if replace_region:
                    active.request_screenshot()
                raise BrowserError("Page capture timed out")
            return CaptureContent(
                page=PageContent(
                    url=tab.url,
                    title=tab.title,
                    width=800,
                    height=600,
                    scroll_y=0,
                    page_height=600,
                ),
                image=_PNG if screenshots else None,
            )

    model = ScriptedModel(["Recovered", "Done"])
    agent = Agent(
        model=model,
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            BrowserPerception(
                capture=FailingCapture(),
                renderer=DomRenderer(),
                screenshots=Screenshots(),
            ),
        ],
    )
    async with agent.session() as session:
        active = session.scope[BrowserPerception]
        active.request_screenshot(original)
        with pytest.raises(BrowserError, match="Page capture timed out"):
            await session.run("Observe")
        result = await session.run("Observe again")
    assert result.text == "Done"
    assert attempts[:2] == [
        (True, original),
        (True, None if replace_region else original),
    ]
    assert any(
        isinstance(part, ImagePart)
        for message in model.requests[0].messages
        if not isinstance(message.content, str)
        for part in message.content
    )


@pytest.mark.parametrize("image_available", [True, False])
async def test_explicit_screenshot_reports_reuse_or_unavailability(image_available):
    class Capture(CaptureStrategy):
        async def collect(self, tab, _report, *, screenshots, **_options):
            return CaptureContent(
                page=PageContent(
                    url=tab.url,
                    title=tab.title,
                    width=800,
                    height=600,
                    scroll_y=0,
                    page_height=600,
                    text="" if image_available else "Screenshot unavailable.",
                ),
                image=_PNG if screenshots and image_available else None,
            )

    model = ScriptedModel(
        [
            [ModelChunk(tool_call=ToolCall("screenshot", {}))],
            [ModelChunk(tool_call=ToolCall("screenshot", {}))],
            "Done",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            BrowserPerception(
                capture=Capture(),
                renderer=DomRenderer(),
                screenshots=Screenshots(),
            ),
            ScreenshotTools(),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Request two screenshots", max_steps=3)
    assert result.text == "Done"
    messages = model.requests[-1].messages
    receipts = [
        message.text for message in messages if isinstance(message, ToolMessage)
    ]
    assert receipts == ["Screenshot requested.", "Screenshot requested."]
    images = [
        part
        for message in messages
        if not isinstance(message.content, str)
        for part in message.content
        if isinstance(part, ImagePart)
    ]
    assert len(images) == int(image_available)
    if image_available:
        assert any("screen unchanged this step" in message.text for message in messages)
    else:
        assert any(message.text == "Screenshot unavailable." for message in messages)
