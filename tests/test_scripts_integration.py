import json
import re

import pytest

from browserrig import ChromeBrowser, DomCapture, Launch, wait_for_page
from browserrig.core import Point
from browserrig.kinds import CursorStyle
from browserrig.observation import capture
from browserrig.observation.content import extract_content
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_visible_descendant_of_hidden_parent_is_extracted_and_inert_content_is_not(
    site,
):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        markup = (
            '<div style="visibility:hidden">Hidden parent text'
            '<a href="/next" style="visibility:visible">Visible child</a></div>'
            "<div inert><a href='/next'>Inert child</a></div>"
            '<div style="display:contents"><p>Contents text</p></div>'
        )
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        snapshot = await capture(tab, DomCapture(), report)
        assert [element.name for element in snapshot.elements] == ["Visible child"]
        content = await extract_content(tab)
        assert (
            "Visible child" in content.markdown and "Contents text" in content.markdown
        )
        assert (
            "Hidden parent text" not in content.markdown
            and "Inert child" not in content.markdown
        )


@pytest.mark.parametrize("limit", [2, 4, 7, 20, 40, 80])
async def test_truncated_markdown_keeps_code_fences_closed(site, limit):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            "document.body.innerHTML = '<pre><code>'+ 'x'.repeat(500) +'</code></pre>'",
        )
        content = await extract_content(tab, max_chars=limit)
        assert len(content.markdown) <= limit
        fences = re.findall(r"^`{3,}", content.markdown, flags=re.M)
        assert len(fences) % 2 == 0
        assert content.limitations


async def test_frame_heading_budget_does_not_reopen_a_truncated_code_fence(site):
    async with ChromeBrowser(Launch(url=site + "/frames")) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        child = next(frame for frame in await tab.frames() if frame.parent is not None)
        await evaluate(
            child, "document.body.innerHTML = '<pre>'+ 'x'.repeat(500) +'</pre>'"
        )
        content = await extract_content(tab, max_chars=200)
        assert len(content.markdown) <= 200
        assert len(re.findall(r"^`{3,}", content.markdown, flags=re.M)) % 2 == 0


async def test_cursor_probe_reads_css_and_text_cursors_through_shadow_roots(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        markup = (
            "<style>body{margin:0} div,a,input,p{position:absolute;margin:0;width:100px;"
            "height:30px;left:0}</style>"
            '<a href="#" style="top:0">Link</a>'
            '<input style="top:40px">'
            '<p style="top:80px;width:auto">Plain text</p>'
            '<div style="top:120px;cursor:grab">Grab</div>'
            '<div style="top:160px;cursor:url(x.cur),not-allowed"></div>'
            '<div id=host style="top:200px"></div>'
            '<div style="top:240px"></div>'
        )
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await evaluate(
            tab,
            "document.querySelector('#host').attachShadow({mode:'open'}).innerHTML ="
            " '<button style=\"cursor:pointer;width:100px;height:30px\">Shadow</button>'",
        )
        styles = [
            await tab.cursor_style(Point(x=10, y=y))
            for y in (10, 50, 90, 130, 170, 210, 250)
        ]
        assert styles == [
            CursorStyle.POINTER,
            CursorStyle.TEXT,
            CursorStyle.TEXT,
            CursorStyle.GRAB,
            CursorStyle.NOT_ALLOWED,
            CursorStyle.POINTER,
            CursorStyle.DEFAULT,
        ]
