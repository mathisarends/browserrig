import asyncio
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import (
    ActionKind,
    Actions,
    BrowserCoordination,
    BrowserPerception,
    CaptureContent,
    DomRenderer,
    MultiTab,
    PageContent,
    PageReadiness,
    SingleTab,
)
from browserrig.browser import TabInfo
from browserrig.tools import Effect
from tests.fakes import FakeChrome


@pytest.mark.parametrize("mode, overview", [(SingleTab, False), (MultiTab, True)])
async def test_tab_overview_is_collected_only_for_multi_tab(mode, overview):
    holder = {}
    listed = (
        TabInfo(id="tab-1", url="https://example.org/", title="Example", active=True),
        TabInfo(id="other", url="https://private.example/", title="Other page"),
    )

    class PageCapture:
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

    class BlockingCapture:
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
