import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from browserrig.core import Bounds, ReadinessPhase
from browserrig.observation import CaptureContent, CookieBanner, Element, capture
from browserrig.observation.extraction import Extraction
from browserrig.secrets.redaction import Redactor
from tests.fakes import FakeReadiness, FakeTab


@pytest.mark.parametrize(
    "source", ["text", "title", "unbounded_element", "cookie_banners"]
)
@pytest.mark.parametrize("bounded_element", [False, True])
async def test_unlocated_secrets_withhold_images_even_with_other_bounded_hits(
    source, bounded_element
):
    secret = "synthetic-password-123"
    field = Element(
        ref="e1",
        frame_id="f",
        backend_id=1,
        role="textbox",
        tag="input",
        name="Password",
        value=secret,
        bounds=Bounds(x=0, y=0, width=20, height=10),
    )
    elements = [field] if bounded_element else []
    fields = {}
    if source == "unbounded_element":
        elements.append(field.model_copy(update={"ref": "e2", "bounds": None}))
    elif source == "cookie_banners":
        fields[source] = (CookieBanner(text=f"Cookies for {secret}"),)
    else:
        fields[source] = secret
    page = Extraction(
        url="https://example.org",
        title="Login",
        width=100,
        height=50,
        scroll_y=0,
        page_height=50,
        elements=tuple(elements),
    )
    for name, value in fields.items():
        setattr(page, name, value)
    output = BytesIO()
    Image.new("RGB", (100, 50), "white").save(output, format="PNG")
    image = base64.b64encode(output.getvalue()).decode()
    redactor = Redactor()
    redactor.add("pw", secret)
    content = CaptureContent(
        page, image=image, area=Bounds(x=0, y=0, width=100, height=50)
    )
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    snapshot = await capture(
        tab,
        SimpleNamespace(collect=AsyncMock(return_value=content)),
        report,
        screenshots=True,
        redaction=SimpleNamespace(redact=redactor.scrub),
    )
    assert secret not in repr(snapshot)
    assert snapshot.image is None
    assert "Screenshot withheld: it may show a secret" in snapshot.limitations
