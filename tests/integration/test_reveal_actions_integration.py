import asyncio
import json

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel, ScriptedModel

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Chrome,
    Files,
    LocalWorkspace,
    wait_for_page,
)
from browserrig.browser import BrowserEvents
from browserrig.core import ActionKind, Bounds
from browserrig.events import (
    CursorStateEvent,
    FilesUploadedEvent,
    PointerPressedEvent,
    ScrolledEvent,
)
from browserrig.tools import Actions
from browserrig.tools.effects import Effect
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def _mount_control(tab, site, operation, framed):
    control = {
        "click": '<button id=target onclick="this.dataset.clicked=1">Action target</button>',
        "download": (
            f'<a id=target href="{site}/download" download="example.txt">'
            "Action target</a>"
        ),
        "upload": '<input id=target type=file aria-label="Action target">',
        "hidden_upload": (
            "<label id=anchor for=target>Action target</label>"
            '<input id=target type=file hidden aria-label="Action target">'
        ),
        "type": '<input id=target aria-label="Action target">',
        "select": (
            '<select id=target aria-label="Action target">'
            "<option>One</option><option>Two</option></select>"
        ),
        "date": '<input id=target type=date aria-label="Action target">',
    }[operation]
    content = f"""<style>body{{margin:0;height:2600px}}
        #panel{{position:absolute;top:950px;left:20px;width:300px;height:200px;overflow:auto}}
        #content{{height:1200px;position:relative}}
        #target:not([hidden]),#anchor{{position:absolute;top:650px;width:180px;height:32px;display:block}}
        </style><div id=panel><div id=content>{control}</div></div>
        <script>document.querySelector('#panel').scrollTop=600;</script>"""
    if framed:
        await evaluate(
            tab,
            "document.body.innerHTML='<iframe id=outer style=\"position:absolute;"
            "left:80px;top:80px;width:540px;height:340px;border:0;"
            "transform:scale(.8);transform-origin:top left\"></iframe>'",
        )
        outer = (
            '<iframe id=inner style="position:absolute;left:50px;top:35px;'
            "width:400px;height:240px;"
        )
        outer += 'border:0;transform:scale(.9);transform-origin:top left"></iframe>'
        await evaluate(
            tab, f"document.querySelector('iframe').srcdoc={json.dumps(outer)}"
        )
        await wait_for_page(tab)
        await evaluate(
            tab,
            f"document.querySelector('iframe').contentDocument.querySelector('iframe').srcdoc={json.dumps(content)}",
        )
    else:
        await evaluate(
            tab,
            f"document.body.innerHTML={json.dumps(content)};document.querySelector('#panel').scrollTop=600",
        )
    await wait_for_page(tab)


async def _assert_effect(operation, local, browser):
    if operation in {"upload", "hidden_upload"}:
        assert local["files"] == 1
    elif operation == "click":
        assert local["clicked"] == "1"
    elif operation == "type":
        assert local["value"] == "Revealed"
    elif operation == "select":
        assert local["value"] == "Two"
    elif operation == "date":
        assert local["value"] == "2026-11-08"
    else:
        async with asyncio.timeout(5):
            while (
                not (downloads := await browser.downloads())
                or downloads[0].state != "completed"
            ):
                await asyncio.sleep(0.02)
        assert downloads[0].filename == "example.txt"


@pytest.mark.parametrize("framed", [False, True])
@pytest.mark.parametrize(
    "operation",
    ["click", "upload", "hidden_upload", "download", "type", "select", "date"],
)
async def test_element_actions_reveal_scroll_containers_and_project_the_cursor(
    site, tmp_path, framed, operation
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "report.txt").write_text("report")
    called = False

    async def respond(_request):
        nonlocal called
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        # Simulate a page script scrolling after the agent's observation was delivered.
        await evaluate(
            leaf,
            "document.querySelector('#panel').scrollTop=0;window.lastPointer=null;"
            "document.addEventListener('mousemove', e=>window.lastPointer=[e.clientX,e.clientY])",
        )
        tool, arguments = {
            "click": ("click", {}),
            "download": ("click", {}),
            "upload": ("upload_files", {"paths": ["report.txt"]}),
            "hidden_upload": ("upload_files", {"paths": ["report.txt"]}),
            "type": ("type_text", {"text": "Revealed"}),
            "select": ("select_option", {"value": "Two"}),
            "date": ("set_date", {"value": "2026-11-08"}),
        }[operation]
        yield ModelChunk(tool_call=ToolCall(tool, {"ref": target.ref, **arguments}))

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(workspace)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        browser, observe = session.scope[Browser], session.scope[BrowserPerception]
        tab = browser.active_tab
        await wait_for_page(tab)
        await _mount_control(tab, site, operation, framed)
        state = await observe.capture()
        target = next(
            element
            for element in state.elements
            if element.name == "Action target"
            and element.tag
            == {
                "click": "button",
                "download": "a",
                "upload": "input",
                "hidden_upload": "input",
                "type": "input",
                "select": "select",
                "date": "input",
            }[operation]
        )
        handle = await observe.dom_element(tab, target.ref)
        leaf = handle.frame
        events = []

        def record(event):
            events.append(event)
            return event

        remove_filter = session.scope[BrowserEvents].add_filter(record)
        try:
            result = await session.run("Interact with the target", max_steps=2)
        finally:
            remove_filter()
        assert result.text == "Done" and called
        receipts = [
            event.result
            for event in result.events
            if isinstance(event, ToolExecutionFinishedEvent)
        ]
        assert any("Auto-reveal" in receipt.text for receipt in receipts)
        assert receipts and all(not receipt.is_error for receipt in receipts), (
            [receipt.text for receipt in receipts],
            await evaluate(
                leaf,
                "({page:scrollY,panel:document.querySelector('#panel').scrollTop,"
                "target:document.querySelector('#target').getBoundingClientRect().toJSON()})",
            ),
            [event for event in events if isinstance(event, ScrolledEvent)],
        )
        local = await evaluate(
            leaf,
            """(() => {
            const target=document.querySelector('#anchor')||document.querySelector('#target');
            const r=target.getBoundingClientRect();
            return {box:{x:r.x,y:r.y,width:r.width,height:r.height},
                pointer:lastPointer,scroll:document.querySelector('#panel').scrollTop,
                value:document.querySelector('#target').value,
                clicked:document.querySelector('#target').dataset.clicked,
                files:document.querySelector('#target').files?.length};
        })()""",
        )
        assert local["scroll"] > 0 and local["pointer"] is not None, (
            local,
            [receipt.text for receipt in receipts],
        )
        assert Bounds.model_validate(local["box"]).contains(*local["pointer"])
        await _assert_effect(operation, local, browser)
        # Receipt coordinates must be in the main viewport, not iframe-local pixels.
        live = await observe.dom_element(tab, target.ref)
        viewport_box = live.frame.transform.bounds_to_viewport(
            Bounds.model_validate(local["box"])
        )
        relevant = next(
            event
            for event in reversed(events)
            if isinstance(event, CursorStateEvent)
            and viewport_box.contains(event.x, event.y)
        )
        assert 0 <= relevant.x < state.width and 0 <= relevant.y < state.height
        if operation in {"click", "download"}:
            pressed = next(
                event for event in events if isinstance(event, PointerPressedEvent)
            )
            assert viewport_box.contains(pressed.x, pressed.y)
        if operation in {"upload", "hidden_upload"}:
            uploaded = next(
                event
                for event in result.events
                if isinstance(event, FilesUploadedEvent)
            )
            assert uploaded.ref == target.ref


async def test_same_action_reprojects_after_programmatic_iframe_motion(site):
    agent = Agent(model=ScriptedModel(["Unused"]), browser=Chrome.launch(url=site))
    async with agent.session() as session:
        browser, observe, actions = (
            session.scope[Browser],
            session.scope[BrowserPerception],
            session.scope[Actions],
        )
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            "document.body.innerHTML='<iframe style=\"position:absolute;left:40px;"
            "top:60px;width:300px;height:200px\"></iframe>'",
        )
        await evaluate(
            tab,
            "document.querySelector('iframe').srcdoc='<button "
            'onclick="this.dataset.clicked=1">Moving frame</button>\'',
        )
        await wait_for_page(tab)
        state = await observe.capture()
        ref = next(
            element.ref for element in state.elements if element.name == "Moving frame"
        )
        points = []

        async def click(_tab):
            points.append(await actions.element_point(tab=tab, ref=ref))
            await evaluate(
                tab,
                "document.querySelector('iframe').style.left='350px';document.querySelector('iframe').style.top='160px'",
            )
            points.append(await actions.element_point(tab=tab, ref=ref, scroll=False))
            await browser.input.mouse.click(points[-1])
            return Effect("Clicked")

        result = await actions.run(kind=ActionKind.CLICK, operation=click)
        assert not result.is_error and points[1].x - points[0].x == pytest.approx(310)
        assert points[1].y - points[0].y == pytest.approx(100)
        handle = await observe.dom_element(tab, ref)
        assert (
            await evaluate(
                handle.frame, "document.querySelector('button').dataset.clicked"
            )
            == "1"
        )
