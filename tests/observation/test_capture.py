import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify import CDPCommandError

from browserrig.core import Bounds, BrowserError, ReadinessPhase, StaleElement
from browserrig.observation import (
    CaptureContent,
    CookieBanner,
    DomCapture,
    Element,
    capture,
    decision_change,
)
from browserrig.observation.extraction import Extraction
from browserrig.observation.models import ElementFingerprint, PageFingerprint
from tests.fakes import FakeReadiness, FakeTab

capture_module = import_module("browserrig.observation.capture")


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


async def test_capture_restarts_with_the_new_document_and_discards_old_content():
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _RacingCapture(["navigate", None])
    snapshot = await capture(tab, strategy, report)
    assert strategy.calls == 2
    assert snapshot.document_id == snapshot.text == "doc-1-next"
    assert snapshot.url == "https://example.org/next"
    assert (
        snapshot.readiness == "degraded"
        and "Document changed" in snapshot.readiness_reason
    )


@pytest.mark.parametrize("wrapped", [False, True])
async def test_capture_retries_a_destroyed_context_including_snapshot_errors(wrapped):
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    error = CDPCommandError(
        "DOMSnapshot.captureSnapshot", -32000, "Execution context was destroyed"
    )
    if wrapped:
        outer = BrowserError("Page snapshot failed")
        outer.__cause__ = error
        error = outer
    strategy = _RacingCapture([error, None])
    snapshot = await capture(tab, strategy, report)
    assert strategy.calls == 2 and snapshot.text == "doc-1"
    assert snapshot.readiness == "ready"


async def test_capture_retries_a_repeated_race_only_once():
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _RacingCapture(["navigate", "navigate", None])
    with pytest.raises(StaleElement, match="Document changed"):
        await capture(tab, strategy, report)
    assert strategy.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        BrowserError("broken capture"),
        CDPCommandError("DOMSnapshot.captureSnapshot", -32000, "unavailable"),
        asyncio.CancelledError(),
    ],
)
async def test_capture_does_not_retry_unrelated_errors_or_cancellation(error):
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _RacingCapture([error, None])
    with pytest.raises(type(error)):
        await capture(tab, strategy, report)
    assert strategy.calls == 1


async def test_exhausted_readiness_does_not_start_another_capture_attempt():
    tab = FakeTab()
    report = (
        await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    ).model_copy(update={"timed_out": True, "status": "degraded"})
    strategy = _RacingCapture(["navigate", None])
    snapshot = await capture(tab, strategy, report)
    assert strategy.calls == 1
    assert not snapshot.elements and snapshot.image is None
    assert "still loading" in snapshot.text


async def test_capture_retry_remains_bounded_and_cancels_stalled_work(monkeypatch):
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    strategy = _RacingCapture(["navigate", "stall"])
    # Keep the deadline small without relying on elapsed-time assertions.
    monkeypatch.setattr(capture_module, "_CAPTURE_SECONDS", 0.1)
    with pytest.raises(BrowserError, match="capture timed out"):
        async with asyncio.timeout(1):
            await capture(tab, strategy, report)
    assert strategy.calls == 2 and strategy.cancelled


@pytest.mark.parametrize("stalled", [False, True])
async def test_optional_screenshot_failure_retains_the_dom_and_cancels_stalled_work(
    monkeypatch, stalled
):
    tab = FakeTab()
    report = await FakeReadiness().wait(tab, phase=ReadinessPhase.OBSERVATION)
    page = (await _Capture().collect(tab, report, screenshots=False)).page
    frame = SimpleNamespace(visible=Bounds(x=0, y=0, width=1280, height=800))
    tab.frames = AsyncMock(return_value=(frame,))
    tab.frame_limitations = ()
    extracted = AsyncMock(return_value=page)
    cancelled = False

    async def screenshot(_tab, _geometry):
        nonlocal cancelled
        if not stalled:
            raise CDPCommandError("Page.captureScreenshot", -32000, "unavailable")
        try:
            await asyncio.Future()
        finally:
            cancelled = True

    monkeypatch.setattr(capture_module, "extract", extracted)
    monkeypatch.setattr(capture_module, "screenshot", screenshot)
    monkeypatch.setattr(capture_module, "_SCREENSHOT_SECONDS", 0.02)
    snapshot = await capture(tab, DomCapture(), report, screenshots=True)
    assert snapshot.text == "Example page" and snapshot.elements[0].ref == "1"
    assert (
        snapshot.image is None and "Screenshot unavailable" in snapshot.limitations[-1]
    )
    assert cancelled == stalled
    extracted.assert_awaited_once()
    tab.frames.assert_awaited_once()


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


class _RacingCapture(_Capture):
    def __init__(self, faults):
        super().__init__()
        self.faults = iter(faults)
        self.calls = 0
        self.cancelled = False

    async def collect(self, tab, report, **kwargs):
        self.calls += 1
        fault = next(self.faults, None)
        if isinstance(fault, BaseException):
            raise fault
        if fault == "stall":
            try:
                await asyncio.Future()
            finally:
                self.cancelled = True
        content = await super().collect(tab, report, **kwargs)
        content.page.text = tab.document_id
        if fault == "navigate":
            tab.document_id += "-next"
            tab.url = "https://example.org/next"
        return content
