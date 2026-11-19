import asyncio
import base64

import pytest
from harnessed import Agent, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel

from browserrig import (
    ActionLabels,
    Browser,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    Files,
    Input,
    InputPacing,
    InputRuntime,
    LocalWorkspace,
    Point,
    Runtime,
    Viewport,
    wait_for_page,
)
from browserrig import Agent as BrowserAgent
from browserrig.browser import Frame, screenshot
from browserrig.choreography import (
    AddressBarFocusedEvent,
    BackPressedEvent,
    CursorEnteredEvent,
    FileTransferEvent,
    ToolCallPresentedEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.core import FileTransferDirection
from browserrig.dom.content import (  # smelt: ignore[SMT107] -- test seam
    # Test document extraction independently of capture strategy.
    extract_content,
)
from browserrig.events import (
    ActionFinishedEvent,
    ActionStartedEvent,
    CursorStateEvent,
    DownloadCompletedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
    KeyPressedEvent,
    ScrollStartedEvent,
)
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


class _UploadReceipts(Plugin):
    """The upload publisher boundary; the renderer does not own its events."""

    events = (FilesUploadedEvent,)


async def test_file_cards_wait_for_explicit_completion_receipts(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site),
            Choreography(),
            ChoreographyOverlay(),
            _UploadReceipts(),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(
            DownloadStartedEvent(download_id="file", filename="report.pdf", url=site)
        )
        await asyncio.sleep(0.65)
        assert (
            await _surface(tab, "document.querySelector('#download').dataset.state")
            == "active"
        )
        await tab.emit(
            DownloadCompletedEvent(download_id="file", filename="report.pdf", size=123)
        )
        assert (
            await _surface(tab, "document.querySelector('#download').dataset.state")
            == "completed"
        )
        await tab.emit(
            FileTransferEvent(
                direction=FileTransferDirection.UPLOAD,
                paths=("report.pdf",),
                duration_seconds=0.1,
                x=80,
                y=80,
            )
        )
        await asyncio.sleep(0.25)
        assert (
            await _surface(tab, "document.querySelector('#upload').dataset.state")
            == "active"
        )
        await tab.emit(FilesUploadedEvent(paths=("report.pdf",), ref="upload"))
        assert (
            await _surface(tab, "document.querySelector('#upload').dataset.state")
            == "completed"
        )


async def test_scroll_feedback_is_visible_during_native_wheel_input(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site),
            Choreography(),
            ChoreographyOverlay(),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        assert (await wait_for_page(tab)).status == "ready"
        observed = []

        async def started(_event: ScrollStartedEvent):
            observed.append(await evaluate(tab, "scrollY"))
            assert (
                await _surface(
                    tab, "document.querySelector('#cursor').dataset.scrolling"
                )
                == "true"
            )

        session.scope.on(ScrollStartedEvent, started, priority=10)
        await session.scope[Input].mouse.scroll(delta_y=500, point=Point(x=500, y=400))
        assert observed == [0]
        # The input reply can precede compositing, especially with a one-step motor.
        async with asyncio.timeout(3):
            while (scroll_y := await evaluate(tab, "scrollY")) <= 450:
                await asyncio.sleep(0.01)
        assert scroll_y > 450


async def test_keyboard_fits_a_compact_viewport_and_keeps_secret_keys_private(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site, viewport=Viewport(width=360, height=640)),
            Choreography(),
            ChoreographyOverlay(keyboard_layout="de"),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        tab = browser.active_tab
        await session.scope[Input].mouse.move_to(Point(x=300, y=600))
        await tab.emit(KeyPressedEvent(key="•", duration_seconds=2))
        result = await _surface(
            tab,
            """(() => {
            const keyboard = document.querySelector('#keyboard').getBoundingClientRect();
            return {left:keyboard.left,right:keyboard.right,top:keyboard.top,bottom:keyboard.bottom,
              active:document.querySelectorAll('[data-pressed="true"]').length,
              protected:document.querySelector('#keyboard').dataset.protected};
        })()""",
        )
        assert 0 <= result["left"] < result["right"] <= 360
        assert 0 <= result["top"] < result["bottom"] <= 640
        assert result["active"] == 0 and result["protected"] == "true"


async def test_toolbar_presses_lead_the_pointer_to_the_drawn_controls(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site),
            Choreography(),
            ChoreographyOverlay(),
        ],
    )
    pointer = """(() => {
        const cursor = document.querySelector('#cursor');
        const at = new DOMMatrix(getComputedStyle(cursor).transform);
        const target = (id) => document.querySelector(id).getBoundingClientRect();
        return {style: cursor.dataset.style, x: at.m41, y: at.m42,
          address: document.querySelector('#address').dataset.visible,
          history: document.querySelector('#history').dataset.visible,
          bar: target('#address-text').toJSON(), icon: target('#history-icon').toJSON()};
    })()"""
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(CursorStateEvent(x=300, y=400))
        await tab.emit(
            AddressBarFocusedEvent(from_position=(300, 400), duration_seconds=0)
        )
        focused = await _settled(tab, pointer, lambda state: _inside(state, "bar"))
        assert focused["style"] == "text" and focused["address"] == "true"

        await tab.emit(BackPressedEvent(from_position=(300, 400), duration_seconds=0))
        pressed = await _settled(tab, pointer, lambda state: _inside(state, "icon"))
        assert pressed["style"] == "pointer" and pressed["history"] == "true"

        await tab.emit(CursorEnteredEvent(to_position=(300, 400), duration_seconds=0))
        returned = await _settled(tab, pointer, lambda state: state["x"] == 300)
        assert returned["style"] != "pointer" and returned["y"] == 400


async def test_long_cursor_badge_stays_inside_a_compact_viewport(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site, viewport=Viewport(width=360, height=640)),
            Choreography(),
            ChoreographyOverlay(name="W" * 40),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        assert (await wait_for_page(tab)).status == "ready"
        for x, y in ((3, 3), (357, 637)):
            await tab.emit(CursorStateEvent(x=x, y=y))
            bounds = await _surface(
                tab,
                """(() => {
                const r=document.querySelector('#cursor-name').getBoundingClientRect();
                return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};
            })()""",
            )
            assert 0 <= bounds["left"] < bounds["right"] <= 360
            assert 0 <= bounds["top"] < bounds["bottom"] <= 640


@pytest.mark.parametrize("local_renderer", [False, True])
async def test_work_stream_is_complete_with_and_without_local_rendering(
    site, tmp_path, local_renderer
):
    calls = [
        ToolCall("write_file", {"path": "notes.md", "content": "Research notes"}),
        ToolCall("read_file", {"path": "notes.md"}),
        ToolCall("list_files", {}),
        ToolCall("execute_javascript", {"code": "({answer: 42})"}),
        ToolCall("screenshot", {}),
    ]
    agent = BrowserAgent(
        model=ScriptedModel(
            [*([ModelChunk(tool_call=call)] for call in calls), "Done"]
        ),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing,)
        if local_renderer
        else (InputPacing, ChoreographyOverlay),
    )
    receipts = []
    async with agent.session() as session:
        session.scope.on(WorkPresentedEvent, receipts.append)
        result = await session.run("Read and extract the research material")
        assert result.text == "Done"
        assert not any(isinstance(event, WorkPresentedEvent) for event in result.events)
        for call in calls:
            updates = [receipt for receipt in receipts if receipt.call_id == call.id]
            assert updates[0].phase is WorkPhase.RUNNING
            assert updates[-1].phase is WorkPhase.COMPLETED
            assert updates[-1].browser_id and updates[-1].target_id
        read = [receipt for receipt in receipts if receipt.call_id == calls[1].id][-1]
        assert read.preview == "Research notes"
        capture = [receipt for receipt in receipts if receipt.call_id == calls[-1].id][
            -1
        ]
        assert capture.image_url.startswith("data:image/jpeg;base64,")
        assert capture.region.width > 0
        tab = session.scope[Browser].active_tab
        tree = await tab.frame_tree()
        assert bool(tree.child_frames) is local_renderer
        if local_renderer:
            assert (
                await _surface(
                    tab, "document.querySelector('#caption-icon img').naturalWidth"
                )
                <= 320
            )


async def test_work_caption_is_inert_text_and_is_excluded_from_extraction(site):
    agent = BrowserAgent(model=ScriptedModel([]), browser=Chrome.launch(url=site))
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        markup = '<img src=x onerror="parent.injected=true">'
        await tab.emit(
            WorkPresentedEvent(
                work_id="preview",
                kind="read_file",
                title=markup,
                phase=WorkPhase.COMPLETED,
                preview=markup,
            )
        )
        assert (
            await _surface(tab, "document.querySelector('#caption-title').textContent")
            == markup
        )
        assert await _surface(
            tab, "document.querySelector('#caption-copy img') === null"
        )

        content = await extract_content(tab)
        assert markup not in content.markdown


async def test_simultaneous_downloads_keep_independent_progress_and_outcomes(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site),
            Choreography(),
            ChoreographyOverlay(),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(
            DownloadStartedEvent(download_id="a", filename="a.pdf", url=site)
        )
        await tab.emit(
            DownloadStartedEvent(download_id="b", filename="b.pdf", url=site)
        )
        await tab.emit(
            DownloadCompletedEvent(download_id="a", filename="a.pdf", size=10)
        )
        state = await _surface(
            tab,
            "[...document.querySelectorAll('#downloads [data-download-id]')]"
            ".map(node => [node.dataset.downloadId, node.dataset.state])",
        )
        assert state == [["a", "completed"], ["b", "active"]]
        await tab.emit(
            FileTransferEvent(
                direction=FileTransferDirection.OPEN,
                paths=("notes.md",),
                duration_seconds=0.01,
            )
        )
        await asyncio.sleep(1.9)
        assert (
            await _surface(tab, "document.querySelector('#opening').dataset.visible")
            == "false"
        )
        assert (
            await _surface(
                tab, "document.querySelector('[data-download-id=b]').dataset.visible"
            )
            == "true"
        )


@pytest.mark.parametrize("theme,width", [("dark", 1280), ("light", 360)])
async def test_work_and_transfers_fit_the_viewport(site, tmp_path, theme, width):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site, viewport=Viewport(width=width, height=740)),
            Choreography(),
            ChoreographyOverlay(theme=theme),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(
            WorkPresentedEvent(
                work_id="report",
                kind="read_file",
                phase=WorkPhase.COMPLETED,
                title="Read research report",
                detail="report.pdf · page 2 / 18 · 8,420 characters",
                preview=(
                    "# Research findings\n\nThe report contains the selected page.\n"
                    "The full extraction remains in the workspace."
                ),
                artifact_path=".content/report-page-2.md",
            )
        )
        await tab.emit(
            DownloadStartedEvent(
                download_id="a", filename="Annual report.pdf", url=site
            )
        )
        boxes = await _surface(
            tab,
            "['#caption', '#downloads'].map(selector => {"
            " const r=document.querySelector(selector).getBoundingClientRect();"
            " return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}; })",
        )
        caption, download = boxes
        assert all(0 <= box["left"] < box["right"] <= width for box in boxes)
        assert (
            caption["right"] <= download["left"] or download["bottom"] <= caption["top"]
        )
        await asyncio.sleep(0.2)
        image = await screenshot(tab, overlays=True)
        (tmp_path / f"work-proof-{theme}-{width}.png").write_bytes(
            base64.b64decode(image)
        )


async def test_running_work_restores_after_navigation_without_pointer_input(site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Runtime(),
            InputRuntime(),
            Chrome.launch(url=site),
            Choreography(),
            ChoreographyOverlay(),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await tab.emit(
            WorkPresentedEvent(
                work_id="read",
                kind="read_file",
                title="Reading report",
                phase=WorkPhase.RUNNING,
            )
        )
        await tab.navigate(site + "/other")
        await wait_for_page(tab)
        assert (
            await _surface(
                tab,
                "document.querySelector('#caption[data-work-id=read]').dataset.phase",
            )
            == "running"
        )
        await tab.emit(
            WorkPresentedEvent(
                work_id="read",
                kind="read_file",
                title="Read report",
                phase=WorkPhase.COMPLETED,
            )
        )
        assert (
            await _surface(
                tab, "document.querySelectorAll('[data-work-id=read]').length"
            )
            == 1
        )
        assert (
            await _surface(
                tab,
                "document.querySelector('#caption[data-work-id=read]').dataset.phase",
            )
            == "completed"
        )


async def test_model_labels_stay_in_the_event_stream_without_changing_overlay(
    site, tmp_path
):
    (tmp_path / "report.txt").write_text("Annual report", encoding="utf-8")
    calls = [
        ToolCall(
            "click_at", {"x": 60, "y": 15, "action_label": "Focusing the email field"}
        ),
        ToolCall(
            "read_file",
            {"path": "report.txt", "action_label": "Reading the annual report"},
        ),
    ]
    agent = BrowserAgent(
        model=ScriptedModel(
            [*([ModelChunk(tool_call=call)] for call in calls), "Done"]
        ),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            ActionLabels(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing,),
    )
    captions = []
    receipts = []
    displayed_calls = []
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await session.scope[Input].mouse.move_to(Point(x=60, y=15))

        async def caption(_event: ToolCallFinishedEvent):
            captions.append(
                await _surface(
                    tab, "document.querySelector('#caption-title').textContent"
                )
            )

        session.scope.on(ToolCallFinishedEvent, caption)
        session.scope.on(WorkPresentedEvent, receipts.append)
        session.scope.on(ToolCallPresentedEvent, displayed_calls.append)
        result = await session.run("Focus the field, then read the report")
    assert captions == ["", ""]
    assert [event.envelope.action_label for event in displayed_calls] == [
        "Focusing the email field",
        "Focusing the email field",
        "Reading the annual report",
        "Reading the annual report",
    ]
    assert not any(receipt.call_id == calls[0].id for receipt in receipts)
    updates = [receipt for receipt in receipts if receipt.call_id == calls[1].id]
    assert updates[0].phase is WorkPhase.RUNNING
    assert updates[-1].phase is WorkPhase.COMPLETED
    assert {receipt.label for receipt in updates} == {"Reading the annual report"}
    assert {receipt.title for receipt in updates} == {"Reading file", "File read"}
    lifecycle = [
        event
        for event in result.events
        if isinstance(event, (ActionStartedEvent, ActionFinishedEvent))
    ]
    assert len(lifecycle) == 2
    assert {event.label for event in lifecycle} == {"Focusing the email field"}
    assert {event.call_id for event in lifecycle} == {calls[0].id}


async def _settled(tab, expression, done, seconds=3):
    """The surface state once `done` holds, as animations finish on the next frames."""
    async with asyncio.timeout(seconds):
        while not done(state := await _surface(tab, expression)):
            await asyncio.sleep(0.05)
    return state


def _inside(state, control) -> bool:
    box = state[control]
    return (
        box["left"] <= state["x"] <= box["right"]
        and box["top"] <= state["y"] <= box["bottom"]
    )


async def _surface(tab, expression):
    """Read only the owned iframe, in its existing isolated world."""
    tree = await tab.frame_tree()
    frame_id = next(
        frame.frame.id
        for frame in tree.child_frames
        if frame.frame.name.startswith("browserrig-overlay-")
    )
    frame = Frame(frame_id, tab.cdp, worlds=tab.worlds)
    return await evaluate(frame, expression)
