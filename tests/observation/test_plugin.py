import asyncio
from unittest.mock import AsyncMock

from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import Actions, BrowserCoordination, BrowserPerception, Readiness
from browserrig.core import ActionKind
from browserrig.observation import CaptureContent, DomRenderer, PageContent
from browserrig.tools.effects import Effect
from tests.fakes import FakeChrome


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
            Readiness(),
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
