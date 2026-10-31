import asyncio
import json

import pytest
from harnessed import Agent, PolicyDecision
from harnessed.models import ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import ChromeBrowser, LaunchBrowser, browser_plugins
from browserrig.events import (
    BarTypedEvent,
    FindBarEvent,
    FindResultsEvent,
    KeyPressedEvent,
    NavigationStartedEvent,
)
from browserrig.kinds import BrowserBar
from browserrig.observation.find import close_find, find_text
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
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
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
    async with ChromeBrowser(LaunchBrowser(url=site + "/frames")) as browser:
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


async def test_find_tool_types_into_the_find_bar_and_reports_matches(site):
    model = ScriptedModel(
        [
            call("navigate", url=site + "/other"),
            call(
                "execute_javascript",
                code=f"document.body.innerHTML = {json.dumps(_GUIDE)}",
            ),
            call("find_in_page", query="widget", match=4, max_results=2),
            call("find_in_page", query="nowhere to be found"),
            call(
                "find_in_page", query="widget", alternatives=["final widget", "gizmo"]
            ),
            "Done",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(LaunchBrowser(url=site)),
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
        await ready.wait()
        result = await session.run("Find the widget", max_steps=6)
    await consumer
    assert result.text == "Done"
    replies = [
        msg for msg in model.requests[-1].messages if isinstance(msg, ToolMessage)
    ]
    assert not any(reply.is_error for reply in replies), [
        reply.text for reply in replies
    ]
    found, missing, either = replies[2].text, replies[3].text, replies[4].text
    assert found.startswith('4 matches for "widget"; match 4 is scrolled into view.')
    # Context stays within the match's paragraph.
    assert found.endswith("\n4. [Late] A final **WIDGET** note.")
    assert "match=" not in found
    assert missing.startswith('No matches for "nowhere to be found"')
    # Alternatives share one numbering; of overlapping matches the earlier one counts.
    assert either.startswith(
        '4 matches for "widget" (3), "final widget" (1) or "gizmo" (0); '
        "match 1 is scrolled into view."
    )
    assert "\n4. [Late] A **final WIDGET** note." in either

    # Live events stream to viewers and stay out of the saved conversation.
    assert not any(isinstance(event, BarTypedEvent) for event in result.events)
    events = streamed
    address = [
        e for e in events if isinstance(e, BarTypedEvent) and e.browser_bar == "address"
    ]
    assert address[-1].key == "Enter" and address[-1].text == address[-2].text
    started = next(
        i for i, e in enumerate(events) if isinstance(e, NavigationStartedEvent)
    )
    assert events.index(address[-1]) < started

    shown = [
        event
        for event in events
        if isinstance(
            event, (KeyPressedEvent, FindBarEvent, BarTypedEvent, FindResultsEvent)
        )
        and getattr(event, "browser_bar", BrowserBar.FIND) == BrowserBar.FIND
    ]
    keys = [(e.key, e.modifiers) for e in shown if isinstance(e, KeyPressedEvent)]
    assert keys == [("f", ("Control",)), ("Escape", ())] * 3
    typed = [e.text for e in shown if isinstance(e, BarTypedEvent)][:6]
    assert typed == ["w", "wi", "wid", "widg", "widge", "widget"]
    results = [
        e for e in shown if isinstance(e, FindResultsEvent) and e.query == "widget"
    ]
    # One update for the last key, then the final one with match 4 scrolled into view.
    assert [(e.total, e.active) for e in results][:2] == [(4, 1), (4, 4)]
    assert 4 in [mark.index for mark in results[1].marks]
    bars = [e.visible for e in shown if isinstance(e, FindBarEvent)]
    assert bars == [True, False] * 3
    bar_text = [e.text for e in shown if isinstance(e, BarTypedEvent)][-1]
    assert bar_text == "widget | final widget | gizmo"
    final = [e for e in shown if isinstance(e, FindResultsEvent)][-1]
    assert (final.query, final.total, final.active) == (bar_text, 4, 1)
    assert all(e.action_id for e in shown)
