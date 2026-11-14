import pytest

from browserrig.observation import search_content
from browserrig.observation.content import PageContent
from browserrig.observation.search import records

_PAGE = """# Reviews

27 records found

| | ID | Nickname | Product | Action |
| --- | --- | --- | --- | --- |
| | 338 | Merrie | Antonia Racer Tank | [Edit](</admin/review/edit/id/338/>) |
| | 337 | Shaunté | Chloe Compete Tank | [Edit](</admin/review/edit/id/337/>) |
| | 340 | Thalia | Breathe-Easy Shirt | [Edit](</admin/review/edit/id/340/>) |

## Products

- [Image](</wireless-earbuds.html>)
  [Wireless Earbuds](</wireless-earbuds.html>)
  $0.01
- Projector Max
  $17,774.32
  - Earbuds holder accessory

Some paragraph about tanks
continues here.
"""


def test_markdown_splits_into_rows_innermost_items_and_paragraphs_in_page_order():
    texts = [record.text for record in records(_PAGE)]
    assert texts == [
        "27 records found",
        "| | 338 | Merrie | Antonia Racer Tank | [Edit](</admin/review/edit/id/338/>) |",
        "| | 337 | Shaunté | Chloe Compete Tank | [Edit](</admin/review/edit/id/337/>) |",
        "| | 340 | Thalia | Breathe-Easy Shirt | [Edit](</admin/review/edit/id/340/>) |",
        "- [Image](</wireless-earbuds.html>) [Wireless Earbuds](</wireless-earbuds.html>)"
        " $0.01",
        "- Projector Max $17,774.32",
        "- Earbuds holder accessory",
        "Some paragraph about tanks continues here.",
    ]


def test_matching_rows_keep_their_table_header_and_section_once():
    found = search_content(_page(), ("tank",), start=0, count=20)
    assert found.total == 3
    assert found.render() == "\n".join(
        [
            '3 records match "tank" on Admin <https://shop.test/reviews>',
            "",
            "## Reviews",
            "",
            "| | ID | Nickname | Product | Action |",
            "| | 338 | Merrie | Antonia Racer Tank | [Edit](</admin/review/edit/id/338/>) |",
            "| | 337 | Shaunté | Chloe Compete Tank | [Edit](</admin/review/edit/id/337/>) |",
            "",
            "## Products",
            "",
            "Some paragraph about tanks continues here.",
        ]
    )


def test_alternatives_ignore_case_accents_and_link_destinations():
    found = search_content(_page(), ("SHAUNTE", "earbuds"), start=0, count=20)
    texts = [record.text for record in found.records]
    assert found.total == 3
    assert texts[0].startswith("| | 337 | Shaunté")
    assert texts[1].startswith("- [Image]") and texts[2] == "- Earbuds holder accessory"
    # The link path contains "review"; the visible text of these rows does not.
    assert search_content(_page(), ("edit/id",), start=0, count=20).total == 0


def test_results_continue_from_start_and_report_what_remains():
    first = search_content(_page(), ("tank",), start=0, count=1)
    assert len(first.records) == 1
    assert first.render().endswith(
        "Showing records 1-1 of 3. 2 more; continue with start=1 or narrow the query."
    )
    rest = search_content(_page(), ("tank",), start=1, count=5)
    assert [record.text[:9] for record in rest.records] == ["| | 337 |", "Some para"]
    assert rest.render().endswith("Showing records 2-3 of 3.")


def test_long_records_show_a_window_around_the_match():
    body = "filler " * 200 + "NEEDLE" + " tail" * 200
    content = PageContent(url="https://shop.test/", title="Long", markdown=body)
    (record,) = search_content(content, ("needle",), start=0, count=1).records
    assert "NEEDLE" in record.text and len(record.text) <= 602
    assert record.text.startswith("…") and record.text.endswith("…")


def test_extraction_limitations_are_reported_with_results():
    content = _page().model_copy(update={"limitations": ("Frame 2 could not be read",)})
    rendered = search_content(content, ("merrie",), start=0, count=5).render()
    assert rendered.endswith("Search limitations:\n- Frame 2 could not be read")


@pytest.mark.parametrize(
    "prefix",
    ["padding " + " " * 1200, "[unrelated](<https://test/needle>) " + "x " * 500],
)
def test_long_record_window_uses_visible_match_position(prefix):
    body = prefix + "NEEDLE" + " tail" * 200
    content = PageContent(url="https://shop.test/", title="Long", markdown=body)
    (record,) = search_content(content, ("needle",), start=0, count=1).records
    assert "NEEDLE" in record.text
    assert len(record.text) <= 602


def test_search_ignores_decomposed_accents():
    content = PageContent(
        url="https://shop.test/", title="Accents", markdown="cafe\u0301s"
    )
    assert search_content(content, ("cafés",), start=0, count=1).total == 1


def test_queries_without_visible_text_are_rejected():
    with pytest.raises(ValueError, match="visible query text"):
        search_content(_page(), (" ",), start=0, count=5)


def _page() -> PageContent:
    return PageContent(url="https://shop.test/reviews", title="Admin", markdown=_PAGE)
