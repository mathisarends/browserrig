import json

import pytest
import yaml
from harnessed import Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Actions, BrowserAgent, ChromeBrowser, DomMode, LaunchBrowser, wait_for_page
from browserrig.events import ActionFinishedEvent
from browserrig.observation.capture import capture
from browserrig.observation.render import render
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


def _state(request):
    return next(
        yaml.safe_load(message.text)
        for message in reversed(request.messages)
        if message.text.startswith("page:\n")
    )


def _element(request, name):
    elements = _state(request)["elements"]
    entry = next((item for item in elements if item["name"] == name), None)
    assert entry is not None, [item["name"] for item in elements]
    return entry


def _assert_tools_succeeded(result):
    receipts = [event.result for event in result.events if isinstance(event, ToolCallFinishedEvent)]
    assert receipts and all(not item.is_error for item in receipts), [
        item.text for item in receipts
    ]


async def test_all_rendered_controls_are_listed_with_explicit_viewport_flags(site):
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
        report = await wait_for_page(browser, tab)
        state = await capture(browser, tab, DomMode(), report)
        assert len(state.elements) == 300
        assert any(element.in_viewport for element in state.elements)
        assert not state.elements[-1].in_viewport
        assert not any("truncated" in item for item in state.limitations)
        entries = yaml.safe_load(render(state))["elements"]
        assert all(isinstance(entry["in_viewport"], bool) for entry in entries)
        assert "text" not in yaml.safe_load(render(state))
        assert await evaluate(tab, "scrollY") == 0
        visual = await capture(browser, tab, DomMode(screenshots=True), report)
        assert all((element.mark is not None) == element.in_viewport for element in visual.elements)
        limited = await capture(browser, tab, DomMode(max_elements=10), report)
        assert len(limited.elements) == 10
        assert any("truncated" in item for item in limited.limitations)


async def test_wheel_preparation_frames_forms_avoids_jitter_and_keeps_pinned_controls_still(site):
    holder = {}
    positions = []
    markup = """<style>body{margin:0;min-height:6000px}
        form{position:absolute;top:1800px;left:40px;width:400px;height:220px}
        label{display:block;margin:12px}#pinned{position:fixed;top:20px;right:20px}
        #far{position:absolute;top:4000px;left:40px}</style>
        <form><label>Far field<input id=field></label>
        <label>Far choice<select id=choice aria-label='Far choice'>
            <option>One</option><option>Two</option></select></label>
        <label>Far date<input id=date type=date></label></form>
        <button id=pinned>Pinned</button><button id=far>Far button</button>"""

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
        ("click", "Far button", {}),
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
        if index == 0:
            assert not entry["in_viewport"]
        yield ModelChunk(tool_call=ToolCall(name, {"ref": entry["ref"], **arguments}))

    agent = BrowserAgent(
        model=CallbackModel(respond),
        browser=LaunchBrowser(url=site),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[Prepare()],
    )
    async with agent.session() as session:
        result = await session.run("Interact with offscreen and pinned controls", max_steps=6)
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        tab = holder["actions"].browser.active_tab
        assert await evaluate(tab, "document.querySelector('#field').value") == "Prepared"
        assert await evaluate(tab, "document.querySelector('#choice').value") == "Two"
        assert await evaluate(tab, "document.querySelector('#date').value") == "2026-10-29"
        wheels = await evaluate(tab, "wheels")
        clicks = await evaluate(tab, "clicks")
        assert len(wheels) > 6 and all(event["trusted"] for event in wheels)
        assert [event["id"] for event in clicks] == ["pinned", "far"]
        assert all(event["trusted"] for event in clicks)
        assert positions[1] > 1000
        assert all(abs(position - positions[1]) < 1 for position in positions[2:5])
        assert positions[-1] > 3000
        receipts = [event for event in result.events if isinstance(event, ActionFinishedEvent)]
        assert len(receipts) == 5
        assert receipts[-1].prepared_scroll
        assert not receipts[-2].prepared_scroll


@pytest.mark.parametrize("modal,horizontal_only", [(False, False), (True, False), (True, True)])
async def test_offscreen_control_inside_vertical_and_horizontal_scroll_container(
    site, modal, horizontal_only
):
    holder = {}
    markup = """<style>body{margin:0;height:5000px}
        #outer{position:absolute;top:1800px;left:50px;width:500px;height:300px;overflow:auto}
        #inner{position:relative;width:1200px;height:1400px}
        button{position:absolute;top:1100px;left:900px}</style>
        <div id=outer><div id=inner><button onclick='document.body.dataset.clicked=event.isTrusted'>
        Nested target</button></div></div>"""

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            await evaluate(
                actions.browser.active_tab, f"document.body.innerHTML = {json.dumps(markup)}"
            )
            if modal:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.documentElement.style.overflow = 'hidden';
                    document.body.style.cssText = 'margin:0;height:100vh;overflow:hidden';
                    document.querySelector('#outer').style.cssText =
                        'position:fixed;top:100px;left:50px;width:500px;height:300px;overflow:auto';
                """,
                )
            if horizontal_only:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.querySelector('#outer').style.overflowY = 'hidden';
                    document.querySelector('button').style.top = '270px';
                """,
                )

    count = 0

    async def respond(request):
        nonlocal count
        entry = _element(request, "Nested target")
        count += 1
        if count == 1:
            assert not entry["in_viewport"]
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
        result = await session.run("Click the nested offscreen target", max_steps=2)
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        tab = holder["actions"].browser.active_tab
        assert await evaluate(tab, "document.body.dataset.clicked") == "true"
        inner_y = await evaluate(tab, "document.querySelector('#outer').scrollTop")
        assert inner_y == 0 if horizontal_only else inner_y > 800
        assert await evaluate(tab, "document.querySelector('#outer').scrollLeft") > 500
        scroll_y = await evaluate(tab, "scrollY")
        assert scroll_y == 0 if modal else scroll_y > 1000


@pytest.mark.parametrize(
    "cross_origin,oversized", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_offscreen_frame_is_scrolled_into_view_before_interaction(
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
                "'position:absolute;top:1800px;left:100px;width:600px;height:240px';"
                f"document.querySelector('iframe').src={json.dumps(origin + '/frame-leaf')};",
            )
            if oversized:
                await evaluate(
                    actions.browser.active_tab,
                    """
                    document.querySelector('iframe').style.cssText =
                        'position:absolute;top:100px;left:0;width:100vw;height:2400px;border:0';
                """,
                )
                frames = await actions.browser.frames(actions.browser.active_tab)
                child = next(frame for frame in frames if frame.parent is not None)
                await evaluate(
                    child,
                    """
                    document.querySelector('button').style.top='1800px';
                """,
                )

    count = 0

    async def respond(request):
        nonlocal count
        entry = _element(request, "Frame button")
        count += 1
        if count == 1:
            assert not entry["in_viewport"]
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
        result = await session.run("Click the target in an offscreen frame", max_steps=2)
        assert result.text == "Done"
        _assert_tools_succeeded(result)
        actions = holder["actions"]
        tab = actions.browser.active_tab
        element = next(el for el in actions.observe.snapshot.elements if el.name == "Frame button")
        frame, _ = await actions.observe.element(tab, element.ref)
        assert await evaluate(frame, "document.body.dataset.clicked") == "true"
        assert await evaluate(tab, "scrollY") > 1000


async def test_prevented_wheel_scroll_does_not_jump_or_click_an_unreached_target(site):
    holder = {}

    class Prepare(Plugin, needs=(Actions,)):
        async def setup(self, actions: Inject[Actions]):
            holder["actions"] = actions
            await evaluate(
                actions.browser.active_tab,
                """
                document.body.innerHTML = '<button style="position:absolute;top:3000px" ' +
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
        receipts = [event for event in result.events if isinstance(event, ToolCallFinishedEvent)]
        assert len(receipts) == 1 and receipts[0].result.is_error
        assert "wheel input" in receipts[0].result.text
        tab = holder["actions"].browser.active_tab
        assert await evaluate(tab, "scrollY") == 0
        assert await evaluate(tab, "document.body.dataset.clicked") is None
