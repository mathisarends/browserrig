import json

import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
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
    InputPacing,
    InputVisualization,
    wait_for_page,
)
from browserrig.browser import Launch
from browserrig.observation import capture, render
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("values", "mode", "expected", "error", "events"),
    [
        (["1", "3"], "normal", ["1", "3"], "", 2),
        (["General", "Wholesale"], "normal", ["1", "2"], "", 2),
        (["1", "General"], "normal", ["1"], "", 2),
        ([], "normal", [], "", 2),
        (["0"], "normal", ["0"], "", 0),
        (["General", "missing"], "normal", ["0"], "not found", 0),
        (["Duplicate"], "normal", ["0"], "ambiguous", 0),
        (["4"], "normal", ["0"], "disabled option", 0),
        (["7"], "normal", ["0"], "disabled option", 0),
        ([], "disabled_selected", ["4"], "disabled option", 0),
        (["1"], "single", ["0"], "native <select multiple>", 0),
        (["1"], "handler_reset", [], "Page handlers changed", 2),
    ],
)
async def test_select_options_replaces_exact_set_or_reports_atomic_failure(
    site, *, values, mode, expected, error, events
):
    holder = {}
    called = False

    async def respond(_request):
        nonlocal called
        if called:
            yield ModelChunk(text="Done")
            return
        called = True
        target = next(
            (
                item
                for item in holder["observe"].snapshot.elements
                if item.name == "Groups"
            ),
            None,
        )
        assert target is not None
        yield ModelChunk(
            tool_call=ToolCall("select_options", {"ref": target.ref, "values": values})
        )

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
        without=(InputPacing, InputVisualization),
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        holder["observe"] = session.scope[BrowserPerception]
        await wait_for_page(tab)
        html = (
            '<select id=groups multiple size=9 aria-label="Groups">'
            "<option value=0 selected>Original</option><option value=1>General</option>"
            "<option value=2>Wholesale</option><option value=3>VIP</option>"
            "<option value=4 disabled>Locked</option><option value=5>Duplicate</option>"
            "<option value=6>Duplicate</option><optgroup label=LockedGroup disabled>"
            "<option value=7>Inside group</option></optgroup></select>"
        )
        await evaluate(
            tab,
            f"document.body.innerHTML={json.dumps(html)};window.received=[];"
            "groups.addEventListener('input',e=>received.push(e.type));"
            "groups.addEventListener('change',e=>received.push(e.type))",
        )
        if mode == "disabled_selected":
            await evaluate(tab, "groups.value='4'")
        elif mode == "single":
            await evaluate(tab, "groups.multiple=false")
        elif mode == "handler_reset":
            await evaluate(tab, "groups.onchange=()=>groups.selectedIndex=-1")
        result = await session.run("Set the requested Groups selection", max_steps=2)
        selected = await evaluate(tab, "Array.from(groups.selectedOptions,o=>o.value)")
        received = await evaluate(tab, "window.received")
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert selected == expected and len(received) == events
    if error:
        assert reply.is_error and error in reply.text
        assert ("dispatch was attempted" if events else "not dispatched") in reply.text
    else:
        assert not reply.is_error
        assert f"Selected {len(expected)} option(s) and verified" in reply.text


async def test_selection_metadata_preserves_explicit_values_ids_groups_and_titles(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <fieldset><legend>Rating</legend>
              <input type=radio id=Rating_5 name="ratings[4]" value=20>
              <label for=Rating_5>★</label>
              <input type=radio id=Rating_1 name="ratings[4]" value=16 checked>
              <label for=Rating_1 title="Lowest score">★</label>
              <input type=radio id=unspecified name=other><label for=unspecified>★</label>
            </fieldset>
            <label>Groups<select multiple><option value=1 selected>General</option>
              <option value=2>Wholesale</option></select></label>
            <input type=password aria-label=Password value=secret>
            <div role=listbox aria-label=Custom aria-multiselectable=true
              style="width:180px;height:40px">Choices</div>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    radios = [item for item in state.elements if item.role == "radio"]
    assert len(radios) == 3
    assert [(item.control_id, item.value, item.checked) for item in radios] == [
        ("Rating_5", "20", False),
        ("Rating_1", "16", True),
        ("unspecified", None, False),
    ]
    assert radios[0].selection_group == radios[1].selection_group == "ratings[4]"
    assert radios[1].description == "Lowest score"
    group = next(item for item in state.elements if item.name == "Groups")
    assert group.multiple and group.options[0].value == "1"
    assert group.options[0].selected and not group.options[1].selected
    assert next(item for item in state.elements if item.name == "Custom").multiple
    assert (
        next(item for item in state.elements if item.name == "Password").value is None
    )
    text = render(state)
    assert 'value="20" id="Rating_5" selection_group="ratings[4]"' in text
    assert 'General value="1"*' in text and "multiple" in text
    assert "5 stars" not in text and "secret" not in text
