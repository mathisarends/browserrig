import pytest

from browserrig import ElementInfo, ElementRef
from browserrig.dom import ContentGroup, Extraction, Heading, render
from browserrig.dom.outline import (  # smelt: ignore[ARC007] -- test seam
    # Verify outline selection independently of plugin activation.
    outline,
)
from browserrig.observation import Snapshot
from tests.snapshots import dom_snapshot


@pytest.mark.parametrize(
    "headings,landmarks,expected,omitted",
    [
        (True, True, ("[MAIN]", "## Pricing", "[DIALOG: Plan]"), ()),
        (False, True, ("[MAIN]", "[DIALOG: Plan]"), ("## Pricing",)),
        (True, False, ("## Pricing", "[DIALOG: Plan]"), ("[MAIN]",)),
        (False, False, ("[DIALOG: Plan]",), ("[MAIN]", "## Pricing")),
    ],
)
def test_outline_keeps_controls_and_dialogs_while_dropping_selected_structure(
    headings, landmarks, expected, omitted
):
    page = outline(_page(), headings=headings, landmarks=landmarks)
    text = render(_snapshot(page))
    assert '[buy] button "Buy"' in text and '[close] button "Close"' in text
    for line in expected:
        assert line in text
    for line in omitted:
        assert line not in text
    assert [element.ref for element in page.elements] == ["buy", "close"]


def test_flat_pages_lose_landmark_sections_but_keep_dialog_sections():
    flat = Extraction(**{**_fields(), "content": None})
    page = outline(flat, headings=False, landmarks=False)
    assert [element.section for element in page.elements] == ["", "DIALOG: Plan"]
    assert page.headings == ()


def _page() -> Extraction:
    return Extraction(**_fields())


def _fields() -> dict:
    return {
        "url": "https://example.org",
        "title": "Shop",
        "width": 1280,
        "height": 800,
        "scroll_y": 0,
        "page_height": 800,
        "elements": (
            ElementInfo(ref="buy", role="button", name="Buy", section="MAIN"),
            ElementInfo(
                ref="close", role="button", name="Close", section="DIALOG: Plan"
            ),
        ),
        "headings": (
            Heading(level=2, text="Pricing", frame_id="frame", section="MAIN"),
        ),
        "content": (
            ContentGroup(
                id="main",
                role="main",
                children=(
                    Heading(level=2, text="Pricing", frame_id="frame"),
                    ElementRef(ref="buy"),
                ),
            ),
            ContentGroup(
                id="dialog",
                role="dialog",
                name="Plan",
                children=(ElementRef(ref="close"),),
            ),
        ),
    }


def _snapshot(page: Extraction) -> Snapshot:
    return dom_snapshot(
        *page.elements,
        url=page.url,
        title=page.title,
        width=page.width,
        height=page.height,
        scroll_y=page.scroll_y,
        page_height=page.page_height,
        headings=page.headings,
        content=page.content,
    )
