import asyncio

import pytest
from cdpify.domains.emulation import MediaFeature
from harnessed import ToolCall
from harnessed.models import ModelChunk
from harnessed.testing import ScriptedModel

from browserrig import (
    Agent,
    Browser,
    Chrome,
    Files,
    InputPacing,
    LocalWorkspace,
    PageExtractionTools,
    Viewport,
)
from browserrig.browser import Frame
from browserrig.choreography import ReadingSweepEvent, WorkPhase, WorkPresentedEvent
from browserrig.choreography.reading import sweep
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


async def test_extract_content_sweeps_once_and_confirms_after_return(site, tmp_path):
    call = ToolCall("extract_content", {})
    agent = Agent(
        model=ScriptedModel([[ModelChunk(tool_call=call)], "Done"]),
        browser=Chrome.launch(url=site, viewport=Viewport(width=640, height=480)),
        plugins=[Files(LocalWorkspace(tmp_path))],
        without=(InputPacing,),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await evaluate(
            tab,
            """document.body.style.width='1500px';
            document.body.innerHTML='<main style="height:2400px"><h1>Saved snapshot</h1>'+
              '<p>Original text</p></main>';
            scrollTo(40,160);
            window.readPositions=[];
            addEventListener('scroll',()=>{
              readPositions.push({y:scrollY,at:performance.now()});
              if(scrollY>1000 && !document.querySelector('#lazy')){
                const extra=document.createElement('p');extra.id='lazy';
                extra.textContent='LAZY_CONTENT_AFTER_EXTRACTION';extra.style.height='1000px';
                document.body.append(extra);
              }
            });""",
        )
        bottom = await evaluate(
            tab,
            "document.scrollingElement.scrollHeight-document.scrollingElement.clientHeight",
        )
        timeline = []

        async def on_sweep(event):
            assert event.work_id == f"tool:{call.id}"
            assert session.scope[PageExtractionTools].extracted_content is not None
            assert (
                await _surface(tab, "document.querySelector('#scan').dataset.state")
                == "sweeping"
            )
            timeline.append("sweep")

        async def on_work(event):
            if event.call_id == call.id and event.phase is WorkPhase.COMPLETED:
                assert await evaluate(tab, "[scrollX,scrollY]") == [40, 160]
                timeline.append("completed")

        session.scope.on(ReadingSweepEvent, on_sweep, priority=10)
        session.scope.on(WorkPresentedEvent, on_work, priority=10)
        result = await session.run("Extract the loaded page")
        assert result.text == "Done" and timeline == ["sweep", "completed"]
        samples = await evaluate(tab, "readPositions")
        positions = [sample["y"] for sample in samples]
        assert max(positions) == bottom
        peak = positions.index(bottom)
        returned = next(
            sample for sample in samples[peak + 1 :] if sample["y"] < bottom
        )
        assert returned["at"] - samples[peak]["at"] >= 200
        assert positions[-1] == 160
        assert await evaluate(tab, "Boolean(document.querySelector('#lazy'))")
        extraction = session.scope[PageExtractionTools].extracted_content
        assert "Original text" in extraction.markdown
        assert "LAZY_CONTENT_AFTER_EXTRACTION" not in extraction.markdown
        assert not any(isinstance(event, ReadingSweepEvent) for event in result.events)
        assert (
            await _surface(tab, "document.querySelector('#caption').dataset.phase")
            == "completed"
        )


async def test_cancelled_reading_restores_position_and_stops_native_scrolling(site):
    agent = Agent(model=ScriptedModel([]), browser=Chrome.launch(url=site))
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await evaluate(tab, "scrollTo(0,120)")
        task = asyncio.create_task(
            sweep(tab, work_id="cancelled", document_id=tab.document_id)
        )
        try:
            async with asyncio.timeout(5):
                while await evaluate(tab, "scrollY") < 200:
                    await asyncio.sleep(0.02)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(2):
                    await task
        assert await evaluate(tab, "scrollY") == 120
        await asyncio.sleep(0.15)
        assert await evaluate(tab, "scrollY") == 120
        assert (
            await evaluate(tab, "typeof globalThis.__browserrig.readingSweep")
            == "undefined"
        )


async def test_reduced_motion_skips_the_reading_scroll(site):
    agent = Agent(model=ScriptedModel([]), browser=Chrome.launch(url=site))
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.cdp.emulation.set_emulated_media(
            features=[MediaFeature(name="prefers-reduced-motion", value="reduce")]
        )
        await evaluate(tab, "scrollTo(0,120)")
        events = []
        session.scope.on(ReadingSweepEvent, events.append)
        await sweep(tab, work_id="reduced", document_id=tab.document_id)
        assert not events and await evaluate(tab, "scrollY") == 120


async def _surface(tab, expression):
    tree = await tab.frame_tree()
    frame_id = next(
        child.frame.id
        for child in tree.child_frames
        if child.frame.name.startswith("browserrig-overlay-")
    )
    return await evaluate(Frame(frame_id, tab.cdp, worlds=tab.worlds), expression)
