import pytest

from browserrig.choreography import (
    ActivityPresentedEvent,
    DownloadPresentedEvent,
    UploadPresentedEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.core import ActionKind, ActivityKind
from browserrig.overlay import (  # smelt: ignore[SMT107] -- test seam
    # Control the receipt clock to reproduce floating-point boundary cases.
    receipts as receipts_module,
)
from browserrig.overlay.receipts import (  # smelt: ignore[SMT107] -- test seam
    # Verify receipt rendering independently of browser staging.
    Receipts,
)


def _work(identity, phase, **values):
    return WorkPresentedEvent(
        work_id=identity,
        kind=ActionKind.READ_FILE,
        title=identity,
        phase=phase,
        **values,
    )


def test_operation_updates_replace_only_the_matching_receipt():
    state = Receipts()
    state.remember(_work("a", WorkPhase.RUNNING))
    state.remember(_work("b", WorkPhase.RUNNING))
    state.remember(_work("a", WorkPhase.COMPLETED))
    current = {event.work_id: event for event in state.snapshot()}
    assert current["a"].phase is WorkPhase.COMPLETED
    assert current["b"].phase is WorkPhase.RUNNING


def test_completion_with_zero_retention_removes_a_running_indicator():
    state = Receipts()
    state.remember(_work("page", WorkPhase.RUNNING))
    state.remember(_work("page", WorkPhase.COMPLETED, retention=0))
    assert not state.snapshot()


def test_download_keeps_one_receipt_and_counts_down_its_retention():
    state = Receipts()
    state.remember(
        DownloadPresentedEvent(download_id="a", filename="r.pdf", phase="running")
    )
    state.remember(
        DownloadPresentedEvent(download_id="a", filename="r.pdf", phase="completed")
    )
    state.remember(UploadPresentedEvent(paths=("x.txt",), target_id="tab"))
    download, upload = state.snapshot()
    assert download.phase is WorkPhase.COMPLETED
    assert 0 < download.retention <= 2.2
    assert 0 < upload.retention <= 8


def test_retention_stays_within_its_budget_at_coarse_clock_boundaries(monkeypatch):
    now = 544.062
    monkeypatch.setattr(receipts_module, "monotonic", lambda: now)
    state = Receipts()
    event = DownloadPresentedEvent(download_id="a", filename="r.pdf", phase="completed")
    state.remember(event)
    (current,) = state.snapshot()
    assert current.retention == event.retention
    now += 1
    (current,) = state.snapshot()
    assert current.retention == pytest.approx(1.2)
    now += 1.3
    assert not state.snapshot()


def test_finished_activity_removes_its_receipt():
    state = Receipts()
    for active in (True, False):
        state.remember(
            ActivityPresentedEvent(
                interval_id="i", kind=ActivityKind.HANDOFF, active=active
            )
        )
    state.remember(
        ActivityPresentedEvent(interval_id="j", kind=ActivityKind.HANDOFF, active=True)
    )
    assert [event.interval_id for event in state.snapshot()] == ["j"]
