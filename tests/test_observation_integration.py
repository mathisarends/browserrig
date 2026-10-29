import base64
import json
from io import BytesIO

import pytest
import yaml
from PIL import Image

from browserrig import ChromeBrowser, DomMode, LaunchBrowser, Viewport, wait_for_page
from browserrig.core.errors import BrowserError
from browserrig.kinds import ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT, capture
from browserrig.observation.render import render

pytestmark = pytest.mark.integration


async def test_composed_dom_semantics_click_listeners_and_visible_text(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await tab.evaluate("""document.body.innerHTML = `
            <div onclick=''><button>Wrapped</button></div>
            <label>Check<input type=checkbox checked></label>
            <fieldset disabled><input aria-label='Disabled by fieldset'></fieldset>
            <div id=listener>Listener only</div>
            <div role=switch aria-checked=true>Switch</div>
            <div contenteditable=plaintext-only aria-label=Editor>Editable</div>
            <div id=closed></div><div id=open><span slot=label>Slotted label</span></div>
            <div style='opacity:0'><button>Transparent ancestor</button></div>
            <div inert><button>Inert ancestor</button></div>
            <div style='position:absolute;top:2000px'>Offscreen text<button>Offscreen</button></div>
            <div style='overflow:hidden;width:1px;height:1px'>
                <button style='margin-left:100px'>Clipped</button></div>
            <div style='position:absolute;left:800px;top:100px'>
                <button>Covered</button>
                <div style='position:absolute;inset:0;background:white'></div>
            </div>`;
            document.querySelector('#listener').addEventListener('click', () => {});
            document.querySelector('#closed').attachShadow({mode:'closed'}).innerHTML =
                '<button>Closed shadow</button>';
            document.querySelector('#open').attachShadow({mode:'open'}).innerHTML =
                '<button><slot name=label></slot></button>';
        """)
        report = await wait_for_page(browser, tab)
        state = await capture(browser, tab, DomMode(max_text_chars=12000), report)
        names = [element.name for element in state.elements]
        for expected in ("Wrapped", "Check", "Listener only", "Switch", "Editor", "Closed shadow"):
            assert names.count(expected) == 1
        assert not {
            "Transparent ancestor",
            "Inert ancestor",
            "Clipped",
            "Covered",
        } & set(names)
        assert not next(
            element for element in state.elements if element.name == "Offscreen"
        ).in_viewport
        assert next(element for element in state.elements if element.name == "Wrapped").in_viewport
        assert "Slotted label" in state.text and "Closed shadow" in state.text
        assert "Offscreen text" not in state.text
        assert not state.limitations
        checked = next(element for element in state.elements if element.name == "Check")
        assert checked.checked is True
        assert next(e for e in state.elements if e.name == "Disabled by fieldset").disabled


@pytest.mark.parametrize("marks", [False, True])
async def test_marks_match_yaml_and_hidpi_screenshot_without_page_mutation(site, marks):
    async with ChromeBrowser(LaunchBrowser(url=site, viewport=Viewport(scale=2))) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        before = await tab.evaluate("document.documentElement.outerHTML")
        state = await capture(browser, tab, DomMode(screenshots=True, marks=marks), report)
        assert await tab.evaluate("document.documentElement.outerHTML") == before
        assert state.image is not None
        with Image.open(BytesIO(base64.b64decode(state.image))) as image:
            assert image.size == (state.width, state.height)
        entries = yaml.safe_load(render(state))["elements"]
        assert len({e["ref"] for e in entries}) == len(entries)
        if marks:
            assert [e["mark"] for e in entries] == list(range(len(entries)))
        else:
            assert all("mark" not in e for e in entries)
        assert "never-echo-this" not in render(state)
        fresh = await capture(browser, tab, DomMode(screenshots=True, marks=marks), report)
        assert fresh.fingerprint == state.fingerprint
        assert fresh.elements[0].ref != state.elements[0].ref
        with pytest.raises(BrowserError, match="STALE_ELEMENT"):
            await (await tab.main_frame()).call(
                ELEMENT_SCRIPT, state.id, state.elements[0].index, ElementOperation.POINT, False
            )


async def test_limits_are_reported_and_checkbox_state_changes_fingerprint(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        await tab.evaluate("document.body.innerHTML = '<label>Toggle<input type=checkbox></label>'")
        before = await capture(browser, tab, DomMode(screenshots=False), report)
        await tab.evaluate("document.querySelector('input').checked = true")
        after = await capture(browser, tab, DomMode(screenshots=False), report)
        assert before.fingerprint != after.fingerprint
        await tab.evaluate(
            "document.body.innerHTML = '<button>First</button><button>Second</button>'"
        )
        limited = await capture(browser, tab, DomMode(max_elements=1, max_text_chars=2), report)
        assert len(limited.elements) == 1 and len(limited.text) <= 2
        assert any("truncated" in limitation for limitation in limited.limitations)


async def test_partially_covered_element_uses_exposed_hit_point(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        markup = """<button style='position:absolute;left:20px;top:20px;width:200px;height:80px'>
            Partial</button><div style='position:absolute;left:80px;top:20px;width:140px;
            height:80px;
            background:white'></div>"""
        await tab.evaluate(f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(browser, tab)
        state = await capture(browser, tab, DomMode(screenshots=False), report)
        element = next(e for e in state.elements if e.name == "Partial")
        point = await (await tab.main_frame()).call(
            ELEMENT_SCRIPT, state.id, element.index, ElementOperation.POINT, False
        )
        assert 20 <= point["x"] < 80
