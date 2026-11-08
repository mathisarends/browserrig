import pytest

from browserrig.core import ReadinessPhase
from browserrig.observation import (
    CaptureContent,
    CookieBanner,
    Element,
    capture,
    decision_change,
)
from browserrig.observation.extraction import Extraction
from browserrig.observation.models import ElementFingerprint, PageFingerprint
from tests.fakes import FakeReadiness, FakeTab


@pytest.mark.parametrize("fingerprint", ["canvas:revision-1", ""])
async def test_strategy_fingerprint_is_used_verbatim_and_tracks_its_own_changes(
    fingerprint,
):
    tab = FakeTab()
    readiness = FakeReadiness()
    report = await readiness.wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _Capture(fingerprint)
    before = await capture(tab, strategy, report)
    assert before.fingerprint == fingerprint
    strategy.fingerprint = "canvas:revision-2"
    after = await capture(tab, strategy, report)
    assert after.fingerprint == "canvas:revision-2"
    assert before.text == after.text and before.elements == after.elements


async def test_capture_without_strategy_fingerprint_keeps_the_dom_digest():
    tab = FakeTab()
    readiness = FakeReadiness()
    report = await readiness.wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _Capture()
    snapshot = await capture(tab, strategy, report)
    expected = PageFingerprint(
        url=tab.url,
        document_id=tab.document_id,
        text=("Example page",),
        scroll_y=25,
        elements=(
            ElementFingerprint(
                role="checkbox",
                name="Enabled",
                value=None,
                disabled=False,
                checked=True,
            ),
        ),
    )
    assert snapshot.fingerprint == expected.digest()
    tab.document_id = "next-document"
    changed = await capture(tab, strategy, report)
    assert changed.fingerprint != snapshot.fingerprint


async def test_cookie_context_survives_capture_and_updates_semantic_fingerprint():
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _Capture()
    before = await capture(tab, strategy, report)
    strategy.banners = (CookieBanner(text="We use cookies.", refs=("1",)),)
    banner = await capture(tab, strategy, report)
    assert banner.cookie_banners == strategy.banners
    assert banner.fingerprint != before.fingerprint
    assert "cookie banner" in decision_change(before, banner)
    strategy.banners = (strategy.banners[0].model_copy(update={"refs": ("other",)}),)
    same = await capture(tab, strategy, report)
    assert same.fingerprint == banner.fingerprint


class _Capture:
    def __init__(self, fingerprint=None):
        self.fingerprint = fingerprint
        self.banners = ()

    async def collect(  # pylint: disable=unused-argument
        self, tab, _report, *, screenshots, region=None, zoom=1, cursor=None
    ):
        return CaptureContent(
            page=Extraction(
                url=tab.url,
                title=tab.title,
                width=1280,
                height=800,
                scroll_y=25,
                page_height=1600,
                text="Example page",
                cookie_banners=self.banners,
                elements=(
                    Element(
                        ref="1",
                        frame_id="frame",
                        backend_id=1,
                        role="checkbox",
                        tag="input",
                        name="Enabled",
                        checked=True,
                    ),
                ),
            ),
            fingerprint=self.fingerprint,
        )
