from browserrig import ElementInfo, ElementRef
from browserrig.dom import ContentGroup, TextBlock, render
from browserrig.observation.delta import (  # smelt: ignore[SMT107] -- test seam
    # Verify model-facing deltas and ref markers independently of capture.
    unmarked,
)
from tests.observations import parse
from tests.snapshots import dom_snapshot, with_dom


def test_inline_refs_survive_parsing_and_new_marker_removal():
    snapshot = _snapshot(
        ElementInfo(ref="opaque:42", role="link", name="a [guide]", new=True),
        content=(
            ContentGroup(
                id="paragraph",
                role="paragraph",
                children=(
                    TextBlock(text="Read", frame_id="frame", trailing_space=True),
                    ElementRef(ref="opaque:42"),
                    TextBlock(text=", then continue.", frame_id="frame"),
                ),
            ),
        ),
    )
    text = render(snapshot)
    assert "text: Read *[a \\[guide\\]][opaque:42], then continue." in text
    assert parse(text)["elements"] == [
        {
            "ref": "opaque:42",
            "role": "link",
            "name": "a [guide]",
            "new": True,
            "in_viewport": True,
        }
    ]
    assert "*[" not in unmarked(text)
    assert parse(unmarked(text))["elements"][0]["new"] is False


def test_paragraph_keeps_current_element_states_and_separate_form_controls():
    snapshot = _snapshot(
        ElementInfo(ref="link", role="link", name="the guide", new=True),
        ElementInfo(ref="submit", role="button", name="Continue", disabled=True),
        content=(
            ContentGroup(
                id="form",
                role="form",
                children=(
                    ContentGroup(
                        id="help",
                        role="paragraph",
                        children=(
                            TextBlock(
                                text="Read", frame_id="frame", trailing_space=True
                            ),
                            ElementRef(ref="link"),
                        ),
                    ),
                    ElementRef(ref="submit"),
                ),
            ),
        ),
    )
    text = render(snapshot)
    assert "text: Read *[the guide][link]" in text
    assert '\n    [submit] button "Continue" disabled' in text
    assert len(parse(text)["elements"]) == 2
    renamed = snapshot.targets[0].model_copy(
        update={"name": "updated guide", "new": False}
    )
    updated = with_dom(snapshot, elements=(renamed, snapshot.targets[1]))
    assert "[updated guide][link]" in render(updated)
    assert "*[" not in render(updated)


def _snapshot(*elements, **fields):
    defaults = {"id": "capture", "title": "Page", "width": 800, "height": 600}
    return dom_snapshot(*elements, **{**defaults, **fields})
