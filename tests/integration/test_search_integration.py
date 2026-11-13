import json

import pytest
from harnessed import ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.testing import ScriptedModel

from browserrig import Agent, Browser, Chrome, wait_for_page
from tests.javascript import evaluate

pytestmark = pytest.mark.integration

_MARKUP = """<main><h1>Reviews</h1>
<table><tr><th>ID</th><th>Nickname</th><th>Product</th><th>Action</th></tr>
<tr><td>338</td><td>Merrie</td><td>Antonia Racer Tank</td>
<td><a href='/edit/338'>Edit</a></td></tr>
<tr><td>340</td><td>Thalia</td><td>Breathe-Easy Shirt</td>
<td><a href='/edit/340'>Edit</a></td></tr></table>
<h2>Products</h2><ol>
<li><a href='/earbuds'>Wireless Earbuds</a><span>$0.01</span></li>
<li><a href='/projector'>Projector Max</a><span>$17,774.32</span></li></ol>
<p hidden>Hidden tank text</p>
<div style='position:absolute;top:4000px'><p>Far below: another tank</p></div>
</main>"""


async def test_search_page_reads_records_beyond_the_viewport_without_scrolling(site):
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(tool_call=ToolCall("search_page", {"query": "tank"})),
                    ModelChunk(tool_call=ToolCall("search_page", {"query": "earbuds"})),
                ],
                "Done",
            ]
        ),
        browser=Chrome.launch(url=site),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(_MARKUP)}")
        await wait_for_page(tab)
        result = await session.run("Search the page")
        scroll = await evaluate(tab, "scrollY")
    tank, earbuds = [
        event.result.text
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert tank.splitlines()[0].startswith('2 records match "tank"')
    assert "| ID | Nickname | Product | Action |" in tank
    assert "| 338 | Merrie | Antonia Racer Tank | [Edit](</edit/338>) |" in tank
    assert "Far below: another tank" in tank and "Hidden tank" not in tank
    assert "[Wireless Earbuds](</earbuds>)" in earbuds and "$0.01" in earbuds
    assert "Projector" not in earbuds
    assert scroll == 0
