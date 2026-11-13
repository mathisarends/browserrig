import asyncio
import json

import pytest
from harnessed import Agent, PolicyDecision, ToolCall
from harnessed.models import ModelChunk, ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Browser, Chrome, ChromeBrowser, browser_plugins
from browserrig.browser import Launch
from browserrig.choreography import BarTypedEvent, FindBarEvent, FindResultsEvent
from browserrig.events import KeyPressedEvent
from browserrig.kinds import BrowserBar
from browserrig.observation import close_find, find_text
from tests.javascript import evaluate

pytestmark = pytest.mark.integration

_GUIDE = """<h1>Guide</h1>
    <h2>Setup</h2><p>Install the Widget first.</p>
    <h2>Usage</h2><p>The wídget   runs anywhere.</p>
    <details><summary>Advanced</summary><p>Hidden widget options</p></details>
    <p style='display:none'>invisible widget</p><input value='widget in a field'>
    <div style='height:3000px'></div>
    <h2>Late</h2><p>A final WIDGET note.</p>"""


async def test_find_matches_rendered_text_opens_collapsed_sections_and_marks_the_viewport(
    site,
):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_GUIDE)}")
        found = await find_text(tab, ("widget",), session="s", count=10)
        # Case, accents and whitespace are ignored; hidden text and field values are not text.
        assert found.total == 4
        assert [match.found.text for match in found.matches] == [
            "Widget",
            "wídget",
            "widget",
            "WIDGET",
        ]
        assert [match.found.heading for match in found.matches] == [
            "Setup",
            "Usage",
            "Usage",
            "Late",
        ]
        assert [match.found.collapsed for match in found.matches] == [
            False,
            False,
            True,
            False,
        ]
        assert "Install the" in found.matches[0].found.before
        assert [mark.index for mark in found.marks] == [1, 2]
        assert not found.scrolled and await evaluate(tab, "scrollY") == 0
        # Matches are marked for viewers only; the page itself is left unpainted.
        assert await evaluate(tab, "CSS.highlights.size") == 0

        collapsed = await find_text(
            tab, ("widget",), session="s", active=2, reveal=True
        )
        assert await evaluate(tab, "document.querySelector('details').open")
        assert 3 in [mark.index for mark in collapsed.marks]

        late = await find_text(
            tab, ("widget",), session="s", active=3, start=3, count=1, reveal=True
        )
        assert late.scrolled and await evaluate(tab, "scrollY") > 1000
        (mark,) = [mark for mark in late.marks if mark.index == 4]
        _, y, width, height = mark.rects[0]
        assert width > 0 and height > 0 and 0 <= y <= await evaluate(tab, "innerHeight")
        assert [match.number for match in late.matches] == [4]

        await close_find(tab)


async def test_find_numbers_matches_across_frames_in_page_order(site):
    async with ChromeBrowser(Launch(url=site + "/frames")) as browser:
        tab = browser.active_tab
        await evaluate(
            tab, "document.body.insertAdjacentHTML('afterbegin', '<p>Inside out</p>')"
        )
        found = await find_text(tab, ("inside",), session="s", count=5)
        assert found.total == 2 and not found.limitations
        assert [match.number for match in found.matches] == [1, 2]
        main, frame = (await tab.frames())[:2]
        assert frame.visible is not None
        # The frame's match is marked where the viewer sees it, inside the iframe.
        (inner,) = [mark for mark in found.marks if mark.index == 2]
        x, y, _, _ = inner.rects[0]
        assert frame.visible.contains(x + 1, y + 1)
        assert main.parent is None


async def test_search_page_shows_the_find_bar_marks_and_ticks_without_scrolling(site):
    model = ScriptedModel(
        [
            call("navigate", url=site + "/other"),
            call(
                "execute_javascript",
                code=f"document.body.innerHTML = {json.dumps(_GUIDE)}",
            ),
            [
                ModelChunk(tool_call=ToolCall("search_page", {"query": "widget"})),
                ModelChunk(
                    tool_call=ToolCall(
                        "search_page",
                        {"query": "nowhere", "alternatives": ["final widget"]},
                    )
                ),
            ],
            "Done",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(browser=Chrome.launch(url=site)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    streamed = []
    ready = asyncio.Event()

    async def consume(session):
        ready.set()
        async for event in session.subscribe(transient=True):
            streamed.append(event)

    async with agent.session() as session:
        consumer = asyncio.create_task(consume(session))
        await asyncio.wait_for(ready.wait(), 30)
        result = await session.run("Search the guide", max_steps=6)
        tab = session.scope[Browser].active_tab
        scroll = await evaluate(tab, "scrollY")
    await asyncio.wait_for(consumer, 30)
    assert result.text == "Done"
    replies = [
        msg for msg in model.requests[-1].messages if isinstance(msg, ToolMessage)
    ]
    assert not any(reply.is_error for reply in replies)
    found, either = replies[2].text, replies[3].text
    # The closed section counts; hidden text and form values do not.
    assert found.startswith('4 records match "widget"')
    assert "A final WIDGET note." in found and "invisible" not in found
    assert either.startswith('1 record matches "nowhere" | "final widget"')
    # Searching never scrolls the page, even to matches far below.
    assert scroll == 0

    shown = [
        event
        for event in streamed
        if isinstance(
            event, (KeyPressedEvent, FindBarEvent, BarTypedEvent, FindResultsEvent)
        )
        and getattr(event, "browser_bar", BrowserBar.FIND) == BrowserBar.FIND
    ]
    keys = [(e.key, e.modifiers) for e in shown if isinstance(e, KeyPressedEvent)]
    assert keys == [("f", ("Control",)), ("Escape", ())] * 2
    assert [e.visible for e in shown if isinstance(e, FindBarEvent)] == [
        True,
        False,
    ] * 2
    typed = [e.text for e in shown if isinstance(e, BarTypedEvent)][:6]
    assert typed == ["w", "wi", "wid", "widg", "widge", "widget"]
    results = [e for e in shown if isinstance(e, FindResultsEvent)]
    first = [e for e in results if e.query == "widget"]
    # Live text matches while typing, then the records the tool returned.
    assert first[-2].label == "4 matches" and first[-1].label == "4 records"
    assert first[-1].marks and max(first[-1].ticks) > 0.8
    assert results[-1].query == "nowhere | final widget"
    assert results[-1].label == "1 record"
