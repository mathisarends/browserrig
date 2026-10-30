import base64
from io import BytesIO

import pytest
from PIL import Image

from browserrig.core.geometry import Bounds, Point
from browserrig.observation.marks import annotate
from browserrig.observation.models import Element


@pytest.fixture(name="screenshot")
def _screenshot():
    output = BytesIO()
    Image.new("RGB", (960, 600), "white").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


@pytest.mark.parametrize("marks", [False, True])
@pytest.mark.parametrize(
    "area,scale,cursor,pixel",
    [
        (Bounds(x=0, y=0, width=320, height=200), 1, Point(x=80, y=60), (80, 60)),
        (Bounds(x=100, y=50, width=200, height=100), 2, Point(x=120, y=80), (40, 60)),
    ],
)
def test_cursor_tip_matches_viewport_and_zoomed_crop_with_or_without_refs(
    screenshot, marks, area, scale, cursor, pixel
):
    elements = (
        (
            Element(
                ref="1",
                frame_id="frame",
                backend_id=1,
                role="button",
                tag="button",
                name="Target",
                bounds=Bounds(x=140, y=100, width=60, height=30),
            ),
        )
        if marks
        else ()
    )
    encoded = annotate(screenshot, elements, area, scale, cursor=cursor)
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (area.width * scale, area.height * scale)
        assert image.getpixel(pixel) == (30, 30, 30)
        assert image.getpixel((pixel[0] + 2 * scale, pixel[1] + 8 * scale)) == (239, 68, 68)


@pytest.mark.parametrize("cursor", [(99, 70), (120, 49), (180, 70), (120, 110)])
def test_cursor_outside_crop_is_omitted(screenshot, cursor):
    area = Bounds(x=100, y=50, width=80, height=60)
    assert annotate(screenshot, (), area, cursor=Point(x=cursor[0], y=cursor[1])) == annotate(
        screenshot, (), area
    )


@pytest.mark.parametrize("cursor", [(0, 0), (319, 199)])
def test_cursor_is_clipped_at_image_edges(screenshot, cursor):
    area = Bounds(x=0, y=0, width=320, height=200)
    encoded = annotate(screenshot, (), area, cursor=Point(x=cursor[0], y=cursor[1]))
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (320, 200)
        assert image.getpixel(cursor) == (30, 30, 30)
