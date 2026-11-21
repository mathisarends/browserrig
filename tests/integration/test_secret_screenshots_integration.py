from types import SimpleNamespace

import pytest

from browserrig import ChromeBrowser, DomModel, wait_for_page
from browserrig.browser import Launch
from browserrig.observation import (  # smelt: ignore[ARC007] -- facade callable
    # Public facade callable; ARC007 confuses it with the same-named module.
    capture,
)
from browserrig.secrets.redaction import (  # smelt: ignore[ARC007] -- test seam
    # Test redaction of text and pixels independently of plugin activation.
    Redactor,
)
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_static_password_echo_is_redacted_and_screenshot_withheld(site):
    secret = "synthetic-password-123"
    redactor = Redactor()
    redactor.add("pw", secret)
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            f"document.body.replaceChildren();document.body.textContent = '{secret}'",
        )
        report = await wait_for_page(tab)
        raw = await capture(tab, DomModel(), report, screenshots=True)
        clean = await capture(
            tab,
            DomModel(),
            report,
            screenshots=True,
            redaction=SimpleNamespace(redact=redactor.scrub),
        )
    assert secret in raw.text and raw.image is not None
    assert secret not in clean.text and "{{secret:pw}}" in clean.text
    assert clean.image is None
