import pytest
import yaml
from pydantic import ValidationError

from browserrig.activity.models import TimeRange, inference_only
from browserrig.browser.config import BrowserKind, ConnectBrowser, LaunchBrowser
from browserrig.events import ActivityFinishedEvent
from browserrig.kinds import ActivityKind
from browserrig.observation.models import Element, ElementFingerprint, PageFingerprint, Snapshot
from browserrig.observation.render import SnapshotView, render


def test_yaml_projection_is_typed_and_omits_internal_routing():
    snapshot = Snapshot(
        id="observation",
        tab_id="tab",
        document_id="document",
        url="https://example.org",
        title="A: title",
        mode="web",
        readiness="ready",
        width=1280,
        height=800,
        scroll_y=0,
        fingerprint="fingerprint",
        elements=(
            Element(
                ref="obs:0",
                frame_id="internal-frame",
                index=42,
                role="button",
                name="!!python/object: surprise",
                tag="button",
            ),
        ),
    )
    text = render(snapshot)
    parsed = SnapshotView.model_validate(yaml.safe_load(text))
    assert parsed.page.title == snapshot.title
    assert "frame_id" not in text and "internal-frame" not in text and "index:" not in text
    assert parsed.elements[0].name == snapshot.elements[0].name


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
            outcome="completed",
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
