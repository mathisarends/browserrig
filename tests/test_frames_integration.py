import json

import pytest
import yaml
from cdpify.exceptions import CDPCommandError
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Actions,
    Browser,
    ChromeBrowser,
    DomMode,
    LaunchBrowser,
    browser_plugins,
    wait_for_page,
)
from browserrig.browser.errors import BrowserError
from browserrig.kinds import ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT, capture

pytestmark = pytest.mark.integration


async def test_frame_extraction_and_old_reference_is_rejected(site):
    async with ChromeBrowser(LaunchBrowser(url=site + "/frames")) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        snapshot = await capture(browser, tab, DomMode(), report)
        inside = next(element for element in snapshot.elements if element.name == "Inside")
        assert inside.frame_id != (await tab.main_frame()).id
        frame = next(frame for frame in await browser.frames(tab) if frame.id == inside.frame_id)
        await frame.call(ELEMENT_SCRIPT, snapshot.id, inside.index, ElementOperation.FOCUS, True)
        await tab.cdp.input.insert_text(text="in an iframe")
        assert await frame.evaluate("document.querySelector('input').value") == "in an iframe"
        await frame.evaluate("document.querySelector('input').remove()")
        with pytest.raises(BrowserError, match="STALE_ELEMENT"):
            await frame.call(
                ELEMENT_SCRIPT, snapshot.id, inside.index, ElementOperation.POINT, None
            )


@pytest.mark.parametrize(
    "cross,nested,transformed,scrolled",
    [
        (False, False, False, False),
        (False, False, True, False),
        (False, True, False, False),
        (False, True, True, False),
        (True, False, False, False),
        (True, True, False, False),
        (True, True, True, False),
        (True, True, True, True),
    ],
)
async def test_frame_refs_route_real_typing_and_trusted_clicks(
    site, cross, nested, transformed, scrolled
):
    holder = {}
    count = 0

    class Prepare(Plugin, needs=(Browser, Actions)):
        async def setup(self, _ctx: Context, browser: Inject[Browser], actions: Inject[Actions]):
            holder.update(browser=browser, actions=actions)
            origin = site.replace("127.0.0.1", "localhost") if cross else site
            path = "/frame-leaf"
            if nested:
                path = "/frame-cross-middle" if cross else "/frame-middle"
            script = f"document.querySelector('iframe').src = {json.dumps(origin + path)};"
            if transformed:
                script += (
                    "document.querySelector('iframe').style.transform = 'scale(.7) rotate(10deg)';"
                )
                script += "document.querySelector('iframe').style.transformOrigin = 'top left';"
            if scrolled:
                script += "document.querySelector('iframe').style.top = '1000px';scrollTo(0,900);"
            await browser.active_tab.evaluate(script)

    async def respond(request):
        nonlocal count
        state = next(
            (
                yaml.safe_load(message.text)
                for message in reversed(request.messages)
                if message.text.startswith("page:\n")
            ),
            None,
        )
        assert state is not None
        assert not state.get("limitations")
        count += 1
        if count == 1:
            entry = next((e for e in state["elements"] if e["name"] == "Frame input"), None)
            assert entry is not None
            yield ModelChunk(
                tool_call=ToolCall("type_text", {"ref": entry["ref"], "text": "Across frames"})
            )
        elif count == 2:
            entry = next((e for e in state["elements"] if e["name"] == "Frame button"), None)
            assert entry is not None
            yield ModelChunk(tool_call=ToolCall("click", {"ref": entry["ref"]}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        plugins=[
            *browser_plugins(
                LaunchBrowser(url=site + "/frame-host", arguments=("--site-per-process",))
            ),
            Prepare(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Fill and click inside the frame", max_steps=3)
        assert result.text == "Done"
        receipts = [
            event for event in session.events if isinstance(event, ToolExecutionFinishedEvent)
        ]
        assert len(receipts) == 2 and all(not event.result.is_error for event in receipts)
        browser, actions = holder["browser"], holder["actions"]
        entry = next(e for e in actions.observe.snapshot.elements if e.name == "Frame button")
        frame, _ = await actions.observe.element(browser.active_tab, entry.ref)
        assert await frame.evaluate("document.querySelector('input').value") == "Across frames"
        assert await frame.evaluate("document.body.dataset.clicked") == "true"
        if cross and not nested:
            assert frame.cdp.session_id != browser.active_tab.cdp.session_id


async def test_hidden_offscreen_and_covered_frames_are_excluded_and_blockers_checked(site):
    async with ChromeBrowser(LaunchBrowser(url=site + "/frame-host")) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        before = await capture(browser, tab, DomMode(screenshots=False), report)
        assert all(e.tag != "iframe" for e in before.elements)
        entry = next(e for e in before.elements if e.name == "Frame button")
        frame = next(frame for frame in await browser.frames(tab) if frame.id == entry.frame_id)
        x, y = frame.projection.point(140, 80)
        await frame.check_point(x, y)
        await tab.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div style=\"position:fixed;inset:0;background:red\"></div>')"
        )
        with pytest.raises(BrowserError, match="ELEMENT_BLOCKED"):
            await frame.check_point(x, y)
        covered = await capture(browser, tab, DomMode(screenshots=False), report)
        assert not covered.elements
        await tab.evaluate(
            "document.body.lastElementChild.remove();document.querySelector('iframe').style.display='none'"
        )
        assert len(await browser.frames(tab)) == 1
        await tab.evaluate(
            "document.querySelector('iframe').style.cssText='display:block;top:2000px'"
        )
        assert len(await browser.frames(tab)) == 1


async def test_unrendered_sibling_does_not_discard_usable_frame(site):
    async with ChromeBrowser(LaunchBrowser(url=site + "/frame-host")) as browser:
        tab = browser.active_tab
        await tab.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            '\'<iframe style="display:none" src="/frame-leaf"></iframe>\')'
        )
        report = await wait_for_page(browser, tab)
        state = await capture(browser, tab, DomMode(screenshots=False), report)
        assert sum(e.name == "Frame button" for e in state.elements) == 1
        assert not state.limitations


async def test_detaching_sibling_retains_root_and_other_frame(site, monkeypatch):
    async with ChromeBrowser(LaunchBrowser(url=site + "/frame-host")) as browser:
        tab = browser.active_tab
        await tab.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<button>Root button</button><iframe id=gone src=/frame-leaf "
            'style="left:750px"></iframe>\')'
        )
        report = await wait_for_page(browser, tab)
        tree = (await tab.cdp.page.get_frame_tree()).frame_tree
        removed_id = tree.child_frames[1].frame.id
        original = type(tab.cdp.dom).get_frame_owner

        async def detach_during_inspection(domain, *, frame_id):
            if frame_id == removed_id:
                await tab.evaluate("document.querySelector('#gone').remove()")
            return await original(domain, frame_id=frame_id)

        monkeypatch.setattr(type(tab.cdp.dom), "get_frame_owner", detach_during_inspection)
        state = await capture(browser, tab, DomMode(screenshots=False), report)
        assert {"Root button", "Frame button"} <= {e.name for e in state.elements}
        assert any(removed_id in limitation for limitation in state.limitations)


async def test_dom_metadata_failure_keeps_native_controls(site, monkeypatch):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)

        async def unavailable(_domain, **_kwargs):
            raise CDPCommandError("DOMSnapshot.captureSnapshot", -32000, "unavailable")

        monkeypatch.setattr(type(tab.cdp.dom_snapshot), "capture_snapshot", unavailable)
        state = await capture(browser, tab, DomMode(screenshots=False), report)
        assert any(e.name == "Email" for e in state.elements)
        assert any(e.name == "Shadow button" for e in state.elements)
        assert any("metadata unavailable" in limitation for limitation in state.limitations)
