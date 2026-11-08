from browserrig.choreography import WorkPhase, WorkPresentedEvent
from browserrig.choreography.receipts import Receipts
from browserrig.core import ActionKind
from browserrig.events import (
    DownloadCompletedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
)


def test_operation_updates_replace_only_the_matching_receipt():
    state = Receipts()
    for identity in ("a", "b"):
        state.remember(
            WorkPresentedEvent(
                work_id=identity,
                kind=ActionKind.READ_FILE,
                title=identity,
                phase=WorkPhase.RUNNING,
            )
        )
    state.remember(
        WorkPresentedEvent(
            work_id="a",
            kind=ActionKind.READ_FILE,
            title="Done",
            phase=WorkPhase.COMPLETED,
        )
    )
    current = {event.work_id: event for event in state.snapshot()}
    assert len(current) == 2
    assert current["a"].phase is WorkPhase.COMPLETED
    assert current["b"].phase is WorkPhase.RUNNING


def test_completion_with_zero_retention_removes_a_running_indicator():
    state = Receipts()
    state.remember(
        WorkPresentedEvent(
            work_id="page",
            kind=ActionKind.WAIT,
            title="Waiting",
            phase=WorkPhase.RUNNING,
        )
    )
    state.remember(
        WorkPresentedEvent(
            work_id="page",
            kind=ActionKind.WAIT,
            title="Ready",
            phase=WorkPhase.COMPLETED,
            retention=0,
        )
    )
    assert not state.snapshot()


def test_completed_download_preserves_its_name_without_stale_progress():
    state = Receipts()
    state.remember(
        DownloadStartedEvent(
            download_id="a", filename="report.pdf", url="https://example.org/report"
        )
    )
    state.remember(DownloadProgressedEvent(download_id="a", received_bytes=10))
    state.remember(
        DownloadStartedEvent(
            download_id="b", filename="other.pdf", url="https://example.org/other"
        )
    )
    state.remember(
        DownloadCompletedEvent(download_id="a", filename="report.pdf", size=20)
    )
    current = state.snapshot()
    assert len(current) == 3
    assert not any(isinstance(event, DownloadProgressedEvent) for event in current)
    assert any(
        isinstance(event, DownloadStartedEvent) and event.download_id == "b"
        for event in current
    )
    assert any(
        isinstance(event, DownloadCompletedEvent) and event.download_id == "a"
        for event in current
    )
