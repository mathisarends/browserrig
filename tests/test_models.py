import pytest
from pydantic import ValidationError

from browserrig.activity.models import TimeRange, inference_only
from browserrig.browser.config import BrowserKind, ConnectBrowser, LaunchBrowser
from browserrig.core.errors import StaleElement
from browserrig.core.geometry import Bounds, Geometry, Region
from browserrig.events import ActivityFinishedEvent
from browserrig.kinds import ActivityKind, ActivityOutcome
from browserrig.observation.models import (
    Canvas,
    Element,
    ElementFingerprint,
    Heading,
    Modal,
    PageFingerprint,
    Snapshot,
)
from browserrig.observation.render import image_caption, render


def _snapshot(*elements: Element, **fields) -> Snapshot:
    return Snapshot(
        id="observation",
        tab_id="tab",
        document_id="document",
        url="https://example.org/shop",
        title="Shop",
        mode="dom",
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
    defaults = {"frame_id": "internal-frame", "backend_id": 1, "role": "button", "tag": "button"}
    return Element(ref=ref, order=order, name=fields.pop("name", ref), **(defaults | fields))


def test_render_lists_visible_elements_by_section_and_group_without_routing_data():
    snapshot = _snapshot(
        _element(
            "1", 0, role="link", tag="a", href="https://example.org/cart?x=1", section="HEADER"
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
            Heading(level=2, text="Login", frame_id="internal-frame", order=1, section="MAIN"),
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


def test_render_summarizes_offscreen_elements_and_reports_modal():
    below = [
        _element(
            str(index),
            index,
            in_viewport=False,
            bounds=Bounds(x=0, y=900 + index, width=10, height=10),
        )
        for index in range(5)
    ]
    snapshot = _snapshot(*below, modal=Modal(role="dialog", name="Cookies"))
    text = render(snapshot, offscreen=2)
    assert 'modal: dialog "Cookies" is open; interact with it first' in text
    assert "below viewport: 5 elements (5 button)" in text
    assert "[0] button" in text and "[1] button" in text and "[2] button" not in text
    assert "scroll 0 of 4000px (0.0 pages above, 4.0 below)" in text


def test_render_lists_canvases_with_viewport_bounds_even_without_elements():
    snapshot = _snapshot(
        canvases=(
            Canvas(frame_id="f", bounds=Bounds(x=100, y=150, width=400, height=200), name="Map"),
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


def test_region_image_is_described_in_render_and_caption():
    geometry = Geometry(x=100, y=150, width=400, height=200, scale=2)
    snapshot = _snapshot(image="png", geometry=geometry)
    assert "image: viewport region x=100 y=150 400x200 at 2x zoom" in render(snapshot)
    assert image_caption(snapshot).endswith(
        "viewport region x=100 y=150 400x200 at 2x zoom; click_at and drag_at take pixels "
        "of this image until the next observation"
    )
    assert image_caption(_snapshot(image="png")) == "Current dom observation observation"


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
    with pytest.raises(StaleElement):
        _snapshot(_element("1", 0)).element("2")


def test_fingerprint_changes_with_semantics_and_url():
    original = PageFingerprint(
        url="https://example.org",
        document_id="doc",
        text=("hello",),
        scroll_y=0,
        elements=(ElementFingerprint(role="button", name="Go", value=None, disabled=False),),
    )
    restored = PageFingerprint.model_validate_json(original.model_dump_json())
    assert restored.digest() == original.digest()
    assert (
        original.model_copy(update={"url": "https://example.org/#new"}).digest()
        != original.digest()
    )
    assert original.model_copy(update={"scroll_y": 5}).digest() != original.digest()


def test_inference_projection_subtracts_overlaps_and_respects_epoch():
    def interval(kind, start, end, epoch="current"):
        return ActivityFinishedEvent(
            interval_id=f"{kind}:{start}",
            kind=kind,
            cause_id="test",
            started_at=start,
            at=end,
            outcome=ActivityOutcome.COMPLETED,
            epoch_id=epoch,
        )

    ranges = inference_only(
        (
            interval(ActivityKind.LLM, 1, 10),
            interval(ActivityKind.TOOL, 3, 5),
            interval(ActivityKind.READINESS, 4, 7),
            interval(ActivityKind.PAUSED, 8, 9),
            interval(ActivityKind.TOOL, 1, 10, "old"),
        )
    )
    assert ranges == (
        TimeRange(start=1, end=3),
        TimeRange(start=7, end=8),
        TimeRange(start=9, end=10),
    )
    with pytest.raises(ValidationError):
        TimeRange(start=10, end=1)


def test_configuration_discriminators_are_enums_and_credentials_are_hidden():
    assert LaunchBrowser().kind is BrowserKind.LAUNCH
    connected = ConnectBrowser(endpoint="ws://127.0.0.1:9222/devtools/browser/secret")
    assert connected.kind is BrowserKind.CONNECT
    assert "secret" not in repr(connected)
    with pytest.raises(ValidationError):
        LaunchBrowser(arguments=("--user-data-dir=unexpected",))
