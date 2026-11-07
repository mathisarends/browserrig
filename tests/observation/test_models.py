import pytest
from pydantic import ValidationError

from browserrig.browser import Connect, Launch
from browserrig.core import Bounds, Geometry, Point, Region, StaleElement
from browserrig.observation import (
    BrowserPerception,
    DomCapture,
    Element,
    Snapshot,
    render,
)
from browserrig.observation.models import (
    Canvas,
    ElementFingerprint,
    Heading,
    Modal,
    Offscreen,
    PageFingerprint,
)


def test_render_lists_visible_elements_by_section_and_group_without_routing_data():
    snapshot = _snapshot(
        _element(
            "1",
            0,
            role="link",
            tag="a",
            href="https://example.org/cart?x=1",
            section="HEADER",
        ),
        _element(
            "2",
            2,
            role="textbox",
            tag="input",
            input_type="email",
            name='Say "hi"',
            required=True,
            section="MAIN",
            group='form "Login"',
            new=True,
        ),
        _element("3", 3, role="checkbox", tag="input", checked=False, section="MAIN"),
        headings=(
            Heading(
                level=2,
                text="Login",
                frame_id="internal-frame",
                order=1,
                section="MAIN",
            ),
        ),
    )
    lines = render(snapshot).splitlines()
    body = lines[lines.index("in viewport:") + 1 :]
    assert body == [
        "  [HEADER]",
        '    [1] link "1" -> /cart?x=1',
        "  [MAIN]",
        "    ## Login",
        '    <form "Login">',
        "      *[2] textbox[type=email] \"Say 'hi'\" required",
        '    [3] checkbox "3" unchecked',
    ]
    assert not any("internal-frame" in line for line in lines)


def test_render_merges_link_headings_and_unwraps_search_redirects():
    snapshot = _snapshot(
        _element(
            "1",
            1,
            role="link",
            tag="a",
            name="Result",
            href="https://www.google.com/url?q=https://docs.example.org/a&sa=U",
        ),
        _element(
            "2", 3, role="link", tag="a", name="More", href="https://example.org/more"
        ),
        headings=(
            Heading(level=2, text="Result", frame_id="internal-frame", order=0),
            Heading(level=3, text="Section", frame_id="internal-frame", order=2),
        ),
    )
    lines = render(snapshot).splitlines()
    assert lines[lines.index("in viewport:") + 1 :] == [
        '  ## [1] link "Result" -> https://docs.example.org/a',
        "  ### Section",
        '  [2] link "More" -> /more',
    ]


def test_render_omits_in_page_targets_that_repeat_the_link_name():
    page = "https://example.org/shop#"
    links = [
        ("Climbing history", "Climbing_history"),
        ("[12]", "cite_note-Carter1985-12"),
        ("Back to top", "top"),
    ]
    snapshot = _snapshot(
        *(
            _element(
                str(index), index, role="link", tag="a", name=name, href=page + fragment
            )
            for index, (name, fragment) in enumerate(links)
        )
    )
    lines = render(snapshot).splitlines()
    assert lines[lines.index("in viewport:") + 1 :] == [
        '  [0] link "Climbing history"',
        '  [1] link "[12]"',
        '  [2] link "Back to top" -> #top',
    ]


def test_render_lists_only_the_viewport_and_reports_modal():
    snapshot = _snapshot(_element("1", 0), modal=Modal(role="dialog", name="Cookies"))
    text = render(snapshot)
    assert "cursor: not in this tab yet" in text
    assert "cursor: x=640 y=13 (viewport CSS pixels)" in render(
        snapshot.model_copy(update={"cursor": Point(x=640.2, y=12.6)})
    )
    assert 'modal: dialog "Cookies" is open; interact with it first' in text
    assert "[1] button" in text and "[2]" not in text and "below viewport" not in text
    assert "scroll 0 of 4000px (0.0 pages above, 4.0 below)" in text


def test_render_lists_canvases_with_viewport_bounds_even_without_elements():
    snapshot = _snapshot(
        canvases=(
            Canvas(
                frame_id="f",
                bounds=Bounds(x=100, y=150, width=400, height=200),
                name="Map",
            ),
            Canvas(
                frame_id="f",
                bounds=Bounds(x=0, y=600, width=300, height=200),
                ref="42",
                clipped=True,
            ),
        )
    )
    text = render(snapshot)
    assert '  canvas "Map" x=100 y=150 400x200 center=300,250' in text
    assert "  canvas (ref 42) x=0 y=600 300x200 center=150,700 (visible part)" in text
    assert "image:" not in text


def test_region_image_is_described_in_render():
    geometry = Geometry(x=100, y=150, width=400, height=200, scale=2)
    snapshot = _snapshot(image="png", geometry=geometry)
    assert "image: viewport region x=100 y=150 400x200 at 2x zoom" in render(snapshot)


def test_region_clips_to_viewport_and_caps_zoom():
    viewport = Bounds(x=0, y=0, width=1280, height=800)
    clipped = Region(x=1200, y=700, width=400, height=400).capture(viewport, 2, 2000)
    assert clipped == Geometry(x=1200, y=700, width=80, height=100, scale=2)
    capped = Region(x=0, y=0, width=1280, height=800).capture(viewport, 4, 2000)
    assert capped is not None and capped.scale == pytest.approx(2000 / 1280)
    assert Region(x=1300, y=0, width=10, height=10).capture(viewport, 1, 2000) is None


def test_zoomed_geometry_maps_image_pixels_back_to_viewport():
    geometry = Geometry(x=100, y=150, width=400, height=200, scale=2)
    assert geometry.point(799, 399) == (499.5, 349.5)
    with pytest.raises(ValueError, match="outside"):
        geometry.point(800, 0)


def test_unknown_ref_is_stale():
    with pytest.raises(StaleElement, match="Unknown"):
        _snapshot(_element("1", 0)).element("2")
    offscreen = _snapshot(_element("1", 0)).model_copy(
        update={"offscreen": (Offscreen(ref="2", frame_id="f", backend_id=2),)}
    )
    with pytest.raises(StaleElement, match="outside the viewport"):
        offscreen.element("2")


def test_fingerprint_changes_with_semantics_and_url():
    original = PageFingerprint(
        url="https://example.org",
        document_id="doc",
        text=("hello",),
        scroll_y=0,
        elements=(
            ElementFingerprint(role="button", name="Go", value=None, disabled=False),
        ),
    )
    restored = PageFingerprint.model_validate_json(original.model_dump_json())
    assert restored.digest() == original.digest()
    assert (
        original.model_copy(update={"url": "https://example.org/#new"}).digest()
        != original.digest()
    )
    assert original.model_copy(update={"scroll_y": 5}).digest() != original.digest()


def test_browser_options_hide_credentials_and_reject_owned_flags():
    connected = Connect(endpoint="ws://127.0.0.1:9222/devtools/browser/secret")
    assert "secret" not in repr(connected)
    with pytest.raises(ValidationError):
        Launch(arguments=("--user-data-dir=unexpected",))


@pytest.mark.parametrize(
    "settings",
    [
        {"max_elements": 0},
        {"max_elements": 50001},
        {"max_text_chars": -1},
        {"max_text_chars": 100001},
        {"sparse_text_chars": -1},
        {"sparse_text_chars": 100001},
    ],
)
def test_capture_rejects_invalid_limits(settings):
    with pytest.raises(ValidationError):
        DomCapture(**settings)


def test_default_observation_explains_sparse_text_without_enabling_screenshots():
    observe = BrowserPerception()
    instructions = observe.renderer.instructions(observe.screenshots)
    assert "When the viewport holds few controls" in instructions
    assert "Screenshots are included only when requested" in instructions


def _snapshot(*elements: Element, **fields) -> Snapshot:
    return Snapshot(
        id="observation",
        tab_id="tab",
        document_id="document",
        url="https://example.org/shop",
        title="Shop",
        readiness="ready",
        width=1280,
        height=800,
        scroll_y=0,
        page_height=4000,
        fingerprint="fingerprint",
        elements=elements,
        **fields,
    )


def _element(ref: str, order: int, **fields) -> Element:
    defaults = {
        "frame_id": "internal-frame",
        "backend_id": 1,
        "role": "button",
        "tag": "button",
    }
    return Element(
        ref=ref, order=order, name=fields.pop("name", ref), **(defaults | fields)
    )
