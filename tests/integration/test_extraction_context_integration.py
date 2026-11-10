import json

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Chrome,
    ChromeBrowser,
    DomCapture,
    Viewport,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.core import ReadinessPhase
from browserrig.observation import capture, render
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_vertical_preview_is_bounded_and_separate_from_the_real_viewport(site):
    async with ChromeBrowser(
        Launch(url=site, viewport=Viewport(width=800, height=600))
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <style>body{margin:0;height:4000px}button,h2,p{position:absolute;left:20px}</style>
            <button style="top:20px">Far above</button>
            <h2 style="top:320px">Previous section</h2>
            <button style="top:400px">Above</button><p style="top:450px">Earlier guidance</p>
            <button style="top:1250px">Visible</button><p style="top:1320px">Current guidance</p>
            <h2 style="top:2100px">Next section</h2>
            <button style="top:2200px">Below</button><p style="top:2250px">Upcoming guidance</p>
            <button style="top:3000px">Far below</button>`; scrollTo(0,1200);""",
        )
        report = await wait_for_page(tab)
        assert await evaluate(
            tab, "document.body.textContent.includes('Current guidance')"
        )
        state = await capture(tab, DomCapture(), report)
        elements = {element.name: element for element in state.elements}
        assert set(elements) == {"Above", "Visible", "Below"}
        assert elements["Visible"].in_viewport
        assert (
            not elements["Above"].in_viewport
            and elements["Above"].outside_viewport == "above"
        )
        assert (
            not elements["Below"].in_viewport
            and elements["Below"].outside_viewport == "below"
        )
        assert state.height == 600 and state.scroll_y == 1200
        assert {heading.text for heading in state.headings} == {
            "Previous section",
            "Next section",
        }
        text = render(state)
        assert (
            text.index("in viewport:")
            < text.index("above viewport (preview")
            < text.index("below viewport (preview")
        )
        assert all(
            value in state.text
            for value in ("Current guidance", "Earlier guidance", "Upcoming guidance")
        )
        strict = await capture(tab, DomCapture(viewport_expansion=0), report)
        assert [element.name for element in strict.elements] == ["Visible"]
        assert "Upcoming guidance" not in strict.text and strict.offscreen


async def test_preview_stays_within_document_edges(site):
    async with ChromeBrowser(
        Launch(url=site, viewport=Viewport(width=800, height=600))
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<style>body{margin:0;height:1800px}
            button{position:absolute;left:20px}</style>
            <button style="top:-300px">Unreachable above</button>
            <button style="top:20px">Top edge</button>
            <button style="top:1700px">Bottom edge</button>
            <button style="position:fixed;top:2000px">Unreachable below</button>`;""",
        )
        report = await wait_for_page(tab)
        top = await capture(tab, DomCapture(), report)
        assert [element.name for element in top.elements] == ["Top edge"]
        await evaluate(tab, "scrollTo(0,document.documentElement.scrollHeight)")
        bottom = await capture(tab, DomCapture(), report)
        assert [element.name for element in bottom.elements] == ["Bottom edge"]
        assert bottom.scroll_y + bottom.height == bottom.page_height


async def test_inner_scroll_targets_report_directions_and_keep_clipped_children_out(
    site,
):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <div id=panel aria-label="Results" style="overflow:auto;width:300px;height:160px">
              <div style="height:900px;position:relative">
                <button>First result</button>
                <button style="position:absolute;top:600px">Clipped result</button>
              </div>
            </div>
            <div aria-label="Carousel" style="overflow:auto;width:200px;height:70px">
              <div style="width:900px;height:50px">Horizontal content</div>
            </div>
            <div style="overflow:hidden;width:100px;height:20px">
              <button style="margin-left:200px">Hard clipped</button>
            </div>`;""",
        )
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        named = {element.name: element for element in state.elements}
        assert not {"Clipped result", "Hard clipped"} & named.keys()
        assert named["Results"].scroll.down >= 700 and named["Results"].scroll.up == 0
        assert named["Carousel"].scroll.right >= 600
        assert "scroll(down=" in render(state) and "scroll(right=" in render(state)
        await evaluate(tab, "document.querySelector('#panel').scrollTop=300")
        moved = await capture(tab, DomCapture(), report)
        panel = next(element for element in moved.elements if element.name == "Results")
        assert (
            panel.scroll.up == 300 and panel.scroll.down < named["Results"].scroll.down
        )
        assert moved.scroll_y == state.scroll_y == 0
        assert moved.fingerprint != state.fingerprint


async def test_dense_form_keeps_guidance_and_probe_omits_the_text_budget(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        markup = (
            "<p id=help>Use your work address; personal accounts cannot be invited.</p>"
        )
        markup += "<label>Email<input aria-describedby=help></label>"
        markup += "".join(
            f"<label>Field {number}<input></label>" for number in range(6)
        )
        await evaluate(tab, f"document.body.innerHTML={json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        field = next(element for element in state.elements if element.name == "Email")
        assert (
            "personal accounts" in state.text
            and "personal accounts" in field.description
        )
        assert "description=" in render(state)
        await evaluate(
            tab,
            "document.body.insertAdjacentHTML('beforeend',"
            "'<p>'+ 'Extra context '.repeat(1000)+'</p>')",
        )
        bounded = await capture(
            tab, DomCapture(max_text_chars=120, sparse_text_chars=0), report
        )
        assert len(bounded.text) <= 120 and any(
            "truncated" in item for item in bounded.limitations
        )
        probe = await capture(
            tab,
            DomCapture(),
            report.model_copy(update={"phase": ReadinessPhase.ACTION}),
        )
        assert probe.text == "" and not probe.limitations


async def test_element_action_reveals_a_preview_before_clicking(site):
    clicked = False

    async def respond(_request):
        nonlocal clicked
        if not clicked:
            clicked = True
            yield ModelChunk(tool_call=ToolCall("click", {"ref": preview.ref}))
        else:
            yield ModelChunk(text="Done")

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
    )
    async with agent.session() as session:
        browser, observe = session.scope[Browser], session.scope[BrowserPerception]
        await wait_for_page(browser.active_tab)
        await evaluate(
            browser.active_tab,
            """document.body.innerHTML = `
            <div style="height:2400px"></div><button style="position:absolute;top:1400px"
              onclick="this.textContent='Clicked'">Preview target</button>`;""",
        )
        state = await observe.capture()
        preview = next(
            element for element in state.elements if element.name == "Preview target"
        )
        assert not preview.in_viewport and preview.outside_viewport == "below"
        result = await session.run("Click the preview target", max_steps=2)
        assert result.text == "Done" and clicked
        assert (
            await evaluate(
                browser.active_tab, "document.querySelector('button').textContent"
            )
            == "Clicked"
        )
        assert await evaluate(browser.active_tab, "scrollY") > 0


async def test_iframe_preview_uses_its_own_visible_scrollport(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        content = """<body style="height:2400px;margin:0">
            <button>Frame visible</button>
            <button style="position:absolute;top:500px">Frame below</button>
            <button style="position:absolute;top:1700px">Frame far below</button></body>"""
        await evaluate(
            tab,
            "document.body.innerHTML='<iframe style=\"width:500px;height:200px\"></iframe>';"
            f"document.querySelector('iframe').srcdoc={json.dumps(content)}",
        )
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        named = {element.name: element for element in state.elements}
        assert named["Frame visible"].in_viewport
        assert (
            not named["Frame below"].in_viewport
            and named["Frame below"].outside_viewport == "below"
        )
        assert "Frame far below" not in named
