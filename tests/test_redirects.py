import base64

import pytest

from browserrig.observation.extraction.accessibility import preferred
from browserrig.observation.redirects import unwrap_redirect


def _bing(target: str) -> str:
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=abc&u=a1{encoded}&ntb=1"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (
            _bing("https://docs.python.org/3/library/asyncio.html"),
            "https://docs.python.org/3/library/asyncio.html",
        ),
        (
            _bing("/images/search?q=asyncio"),
            "https://www.bing.com/images/search?q=asyncio",
        ),
        (
            "https://www.google.de/url?q=https://example.org/a&sa=U",
            "https://example.org/a",
        ),
        (
            "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb&rut=x",
            "https://example.org/b",
        ),
        (
            "https://r.search.yahoo.com/_ylt=A/RV=2/RE=1/RO=10/RU=https%3a%2f%2fexample.org%2fc/RK=2/RS=x-",
            "https://example.org/c",
        ),
    ],
)
def test_search_engine_redirects_resolve_to_their_destination(href, expected):
    assert unwrap_redirect(href) == expected


@pytest.mark.parametrize(
    "href",
    [
        "https://example.org/ck/a?u=a1aHR0cHM6Ly9ldmlsLmV4YW1wbGU",
        _bing("javascript:alert(1)"),
        "https://www.bing.com/ck/a?u=a1%%%",
        "https://www.google.com/search?q=https://example.org",
    ],
)
def test_other_links_and_unsafe_targets_stay_unchanged(href):
    assert unwrap_redirect(href) == href


@pytest.mark.parametrize(
    ("own", "chrome", "expected"),
    [
        ("", "Appearance settings", "Appearance settings"),
        ("(/Stück)", "7,99 € (2,00 €/Stück)", "7,99 € (2,00 €/Stück)"),
        ("Alle", "ALLE", "Alle"),
        ("Issues (176)", "Issues \xa0(176)", "Issues (176)"),
        ("Sucheinstellungen", "Sucheinstellungen ✀", "Sucheinstellungen"),
        ("Small", "", "Small"),
    ],
)
def test_chrome_names_win_unless_they_only_differ_in_presentation(
    own, chrome, expected
):
    assert preferred(own, chrome) == expected
