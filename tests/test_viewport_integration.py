import json
import re

import pytest
from harnessed import Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Actions,
    BrowserAgent,
    ChromeBrowser,
    DomCapture,
    LaunchBrowser,
    wait_for_page,
)
from browserrig.core import StaleElement
from browserrig.events import ActionFinishedEvent
from browserrig.observation import capture, render
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


_LINE = re.compile(r'^\s*\*?\[(?P<ref>[^\]]+)\] \S+ "(?P<name>[^"]*)"')


async def test_only_viewport_controls_are_described_and_the_rest_are_known(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            """
            document.body.innerHTML = Array.from({length:300}, (_, i) =>
                `<button style='display:block;height:30px'>Button ${i}</button>`).join('') +
                '<button hidden>Hidden</button><div inert><button>Inert</button></div>';
        """,
        )
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        assert 0 < len(state.elements) < 300
        assert all(element.in_viewport for element in state.elements)
        assert len(state.elements) + len(state.offscreen) == 300
        assert not any("truncated" in item for item in state.limitations)
        rendered = render(state)
        assert '"Button 0"' in rendered and '"Button 299"' not in rendered
        assert "below viewport" not in rendered and "page text:" not in rendered
        with pytest.raises(StaleElement, match="outside the viewport"):
            state.element(state.offscreen[-1].ref)
        assert await evaluate(tab, "scrollY") == 0
        visual = await capture(tab, DomCapture(), report, screenshots=True)
        assert visual.image is not None
        limited = await capture(tab, DomCapture(max_elements=10), report)
        assert len(limited.elements) == 10
        assert any("truncated" in item for item in limited.limitations)


async def test_wheel_preparation_frames_forms_avoids_jitter_and_keeps_pinned_controls_still(
    site,
):
    holder = {}
    positions = []
    markup = """<style>body{margin:0;min-height:6000px}
        form{position:absolute;top:calc(100vh - 36px);left:40px;width:400px;height:220px}
        label{display:block;margin:12px}#pinned{position:fixed;top:20px;right:20px}</style>
        <form><label>Far field<input id=field></label>
        <label>Far choice<select id=choice aria-label='Far choice'>
            <option>One</option><option>Two</option></select></label>
        <label>Far date<input id=date type=date></label></form>
        <button id=pinned>Pinned</button>"""

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            tab = actions.browser.active_tab
            await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
            await evaluate(
                tab,
                """
                window.wheels=[];window.clicks=[];
                addEventListener('wheel', e => wheels.push({trusted:e.isTrusted,dy:e.deltaY}),
                    {passive:true});
                document.addEventListener('click', e => clicks.push(
                    {id:e.target.id,trusted:e.isTrusted,scroll:scrollY}));
            """,
            )
            await evaluate(
                await tab.main_frame(),
                """
                Element.prototype.scrollIntoView = () => {throw Error('No instant scrolling')};
            """,
            )

    calls = [
        ("type_text", "Far field", {"text": "Prepared"}),
        ("select_option", "Far choice", {"value": "Two"}),
        ("set_date", "Far date", {"value": "2026-10-29"}),
        ("click", "Pinned", {}),
    ]

    async def respond(request):
        tab = holder["actions"].browser.active_tab
        positions.append(await evaluate(tab, "scrollY"))
        index = len(positions) - 1
        if index == len(calls):
            yield ModelChunk(text="Done")
            return
        name, label, arguments = calls[index]
        entry = _element(request, label)
        yield ModelChunk(tool_call=ToolCall(name, {"ref": entry["ref"], **arguments}))

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Prepare()],
    )
    async with agent.session() as session:
        result = await session.run(
            "Interact with edge and pinned controls", max_steps=5
        )
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        tab = holder["actions"].browser.active_tab
        assert (
            await evaluate(tab, "document.querySelector('#field').value") == "Prepared"
        )
        assert await evaluate(tab, "document.querySelector('#choice').value") == "Two"
        assert (
            await evaluate(tab, "document.querySelector('#date').value") == "2026-10-29"
        )
        wheels = await evaluate(tab, "wheels")
        clicks = await evaluate(tab, "clicks")
        assert len(wheels) > 6 and all(event["trusted"] for event in wheels)
        assert [event["id"] for event in clicks] == ["pinned"]
        assert all(event["trusted"] for event in clicks)
        assert positions[1] > 100
        assert all(abs(position - positions[1]) < 1 for position in positions[2:])
        receipts = [
            event for event in result.events if isinstance(event, ActionFinishedEvent)
        ]
        assert len(receipts) == 4
        assert not receipts[-1].prepared_scroll


@pytest.mark.parametrize(
    "modal,horizontal_only", [(False, False), (True, False), (True, True)]
)
async def test_clipped_control_inside_vertical_and_horizontal_scroll_container(
    site, modal, horizontal_only
):
    holder = {}
    markup = """<style>body{margin:0;height:5000px}
        #outer{position:absolute;top:calc(100vh - 40px);left:50px;width:500px;height:300px;
            overflow:auto}
        #inner{position:relative;width:1200px;height:1400px}
        button{position:absolute;top:20px;left:480px}</style>
        <div id=outer><div id=inner><button onclick='document.body.dataset.clicked=event.isTrusted'>
        Nested target</button></div></div>"""

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            await evaluate(
                actions.browser.active_tab,
                f"document.body.innerHTML = {json.dumps(markup)}",
            )
            if modal:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.documentElement.style.overflow = 'hidden';
                    document.body.style.cssText = 'margin:0;height:100vh;overflow:hidden';
                    document.querySelector('#outer').style.cssText =
                        'position:fixed;top:100px;left:50px;width:500px;height:300px;overflow:auto';
                    document.querySelector('button').style.top = '290px';
                """,
                )
            if horizontal_only:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.querySelector('#outer').style.overflowY = 'hidden';
                    document.querySelector('button').style.top = '100px';
                """,
                )

    count = 0

    async def respond(request):
        nonlocal count
        entry = _element(request, "Nested target")
        count += 1
        if count == 1:
            yield ModelChunk(tool_call=ToolCall("click", {"ref": entry["ref"]}))
        else:
            assert entry["in_viewport"]
            yield ModelChunk(text="Done")

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Prepare()],
    )
    async with agent.session() as session:
        result = await session.run("Click the clipped nested target", max_steps=2)
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        tab = holder["actions"].browser.active_tab
        assert await evaluate(tab, "document.body.dataset.clicked") == "true"
        inner_y = await evaluate(tab, "document.querySelector('#outer').scrollTop")
        assert inner_y > 0 if modal and not horizontal_only else inner_y == 0
        assert await evaluate(tab, "document.querySelector('#outer').scrollLeft") > 0
        scroll_y = await evaluate(tab, "scrollY")
        assert scroll_y == 0 if modal else scroll_y > 0


@pytest.mark.parametrize(
    "cross_origin,oversized",
    [(False, False), (True, False), (False, True), (True, True)],
)
async def test_edge_frame_is_scrolled_into_view_before_interaction(
    site, cross_origin, oversized
):
    holder = {}

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            origin = site.replace("127.0.0.1", "localhost") if cross_origin else site
            await evaluate(
                actions.browser.active_tab,
                "document.body.style.height='5000px';"
                "document.querySelector('iframe').style.cssText="
                "'position:absolute;top:calc(100vh - 80px);left:100px;width:600px;height:240px';"
                "new Promise(resolve => {const frame=document.querySelector('iframe');"
                "frame.addEventListener('load', () => resolve(), {once:true});"
                f"frame.src={json.dumps(origin + '/frame-leaf')};" + "})",
            )
            if oversized:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.querySelector('iframe').style.cssText =
                        'position:absolute;top:100px;left:0;width:100vw;height:2400px;border:0';
                """,
                )
                height = await evaluate(actions.browser.active_tab, "innerHeight")
                frames = await actions.browser.active_tab.frames()
                child = next(frame for frame in frames if frame.parent is not None)
                await evaluate(
                    child,
                    f"document.querySelector('button').style.top='{height - 120}px'",
                )

    count = 0

    async def respond(request):
        nonlocal count
        entry = _element(request, "Frame button")
        count += 1
        if count == 1:
            yield ModelChunk(tool_call=ToolCall("click", {"ref": entry["ref"]}))
        else:
            assert entry["in_viewport"]
            yield ModelChunk(text="Done")

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site + "/frames", arguments=("--site-per-process",)),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Prepare()],
    )
    async with agent.session() as session:
        result = await session.run("Click the target in an edge frame", max_steps=2)
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        actions = holder["actions"]
        tab = actions.browser.active_tab
        element = next(
            el for el in actions.observe.snapshot.elements if el.name == "Frame button"
        )
        frame = (await actions.observe.element(tab, element.ref)).frame
        assert await evaluate(frame, "document.body.dataset.clicked") == "true"
        assert await evaluate(tab, "scrollY") > 0


async def test_prevented_wheel_scroll_does_not_jump_or_click_an_unreached_target(site):
    holder = {}

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            await evaluate(
                actions.browser.active_tab,
                """
                document.body.innerHTML =
                    '<button style="position:absolute;top:calc(100vh - 6px)" ' +
                    'onclick="document.body.dataset.clicked=true">Unreached</button>';
                document.body.style.height='5000px';
                addEventListener('wheel', event => event.preventDefault(), {passive:false});
            """,
            )

    count = 0

    async def respond(request):
        nonlocal count
        count += 1
        if count == 1:
            entry = _element(request, "Unreached")
            yield ModelChunk(tool_call=ToolCall("click", {"ref": entry["ref"]}))
        else:
            yield ModelChunk(text="Blocked")

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Prepare()],
    )
    async with agent.session() as session:
        result = await session.run("Attempt the blocked scroll", max_steps=2)
        receipts = [
            event for event in result.events if isinstance(event, ToolCallFinishedEvent)
        ]
        assert len(receipts) == 1 and receipts[0].result.is_error
        assert "wheel input" in receipts[0].result.text
        tab = holder["actions"].browser.active_tab
        assert await evaluate(tab, "scrollY") == 0
        assert await evaluate(tab, "document.body.dataset.clicked") is None


def _state(request):
    text = next(
        message.text
        for message in reversed(request.messages)
        if message.text.startswith("# ") and "\nurl: " in message.text
    )
    elements = []
    in_viewport = False
    for line in text.splitlines():
        if not line.startswith(" "):
            in_viewport = line == "in viewport:"
        match = _LINE.match(line)
        if match:
            elements.append({**match.groupdict(), "in_viewport": in_viewport})
    return elements


def _element(request, name):
    elements = _state(request)
    entry = next((item for item in elements if item["name"] == name), None)
    assert entry is not None, [item["name"] for item in elements]
    return entry


def _assert_tools_succeeded(result):
    receipts = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert receipts and all(not item.is_error for item in receipts), [
        item.text for item in receipts
    ]
