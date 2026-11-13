import asyncio

import pytest
from harnessed.testing import ScriptedModel

from browserrig import Agent, Browser, Chrome
from browserrig.browser import Frame
from browserrig.choreography import WorkPhase, WorkPresentedEvent
from browserrig.core import ActionKind, ActivityKind
from browserrig.events import ActivityStartedEvent, CursorStateEvent
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "phase",
    [WorkPhase.COMPLETED, WorkPhase.WARNING, WorkPhase.FAILED, WorkPhase.CANCELLED],
)
async def test_file_reading_uses_cursor_text_and_keeps_the_native_cursor(site, phase):
    agent = Agent(model=ScriptedModel([]), browser=Chrome.launch(url=site))
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(CursorStateEvent(x=350, y=250))
        icon = await _surface(tab, "document.querySelector('#cursor-icon').innerHTML")
        await tab.emit(
            ActivityStartedEvent(
                interval_id="thinking", kind=ActivityKind.LLM, cause_id="request"
            )
        )
        await tab.emit(
            WorkPresentedEvent(
                work_id="read",
                kind=ActionKind.READ_FILE,
                title="Reading file",
                phase=WorkPhase.RUNNING,
                source_path=r"notes\report.<test>.md",
            )
        )
        assert await _surface(
            tab, "document.querySelector('#cursor-name').textContent"
        ) == ("Reading report.<test>.md")
        assert (
            await _surface(tab, "document.querySelector('#cursor-icon').innerHTML")
            == icon
        )
        assert (
            await _surface(tab, "document.querySelector('#cursor').dataset.thinking")
            == "false"
        )
        assert (
            await _surface(tab, "document.querySelector('#caption').dataset.visible")
            == "false"
        )
        assert (
            await _surface(
                tab, "getComputedStyle(document.querySelector('#flying-file')).display"
            )
            == "none"
        )
        await tab.emit(
            WorkPresentedEvent(
                work_id="read",
                kind=ActionKind.READ_FILE,
                title="Reading file",
                phase=phase,
                source_path=r"notes\report.<test>.md",
            )
        )
        if phase is WorkPhase.COMPLETED:
            assert (
                await _surface(
                    tab, "document.querySelector('#caption').dataset.visible"
                )
                == "false"
            )
            await asyncio.sleep(1.5)
        else:
            assert (
                await _surface(tab, "document.querySelector('#caption').dataset.phase")
                == phase.value
            )
            assert (
                await _surface(
                    tab,
                    "getComputedStyle(document.querySelector('#caption-icon')).display",
                )
                == "none"
            )
        assert (
            await _surface(tab, "document.querySelector('#cursor-name').textContent")
            == "Thinking"
        )


async def _surface(tab, expression):
    tree = await tab.frame_tree()
    frame_id = next(
        child.frame.id
        for child in tree.child_frames
        if child.frame.name.startswith("browserrig-overlay-")
    )
    return await evaluate(Frame(frame_id, tab.cdp, worlds=tab.worlds), expression)
