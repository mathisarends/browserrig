from browserrig.choreography import (
    ActivityPresentedEvent,
    DownloadPresentedEvent,
    UploadPresentedEvent,
    WorkPhase,
)
from browserrig.choreography.status import (  # smelt: ignore[SMT107] -- test seam
    # Test status projection independently of plugin activation.
    StatusProjection,
)
from browserrig.core import ActivityKind, ActivityOutcome
from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    ConnectedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
)


def test_download_receipts_keep_the_filename_from_the_started_fact():
    status = StatusProjection()
    started = status.project(
        DownloadStartedEvent(
            download_id="d", filename="a.pdf", url="https://x/", target_id="tab"
        )
    )
    progressed = status.project(
        DownloadProgressedEvent(download_id="d", received_bytes=10, total_bytes=20)
    )
    failed = status.project(DownloadFailedEvent(download_id="d", reason="x" * 400))
    assert isinstance(started, DownloadPresentedEvent)
    assert (started.filename, started.phase, started.target_id) == (
        "a.pdf",
        WorkPhase.RUNNING,
        "tab",
    )
    assert (progressed.filename, progressed.received_bytes) == ("a.pdf", 10)
    assert failed.filename == "a.pdf" and failed.phase is WorkPhase.FAILED
    assert len(failed.reason) < 400


def test_activities_and_uploads_become_presented_events():
    status = StatusProjection()
    started = status.project(
        ActivityStartedEvent(interval_id="i", kind=ActivityKind.HANDOFF, cause_id="c")
    )
    finished = status.project(
        ActivityFinishedEvent(
            interval_id="i",
            kind=ActivityKind.HANDOFF,
            cause_id="c",
            started_at=0,
            outcome=ActivityOutcome.COMPLETED,
        )
    )
    uploaded = status.project(FilesUploadedEvent(paths=("a.txt",), ref="e1"))
    assert isinstance(started, ActivityPresentedEvent) and started.active
    assert isinstance(finished, ActivityPresentedEvent) and not finished.active
    assert isinstance(uploaded, UploadPresentedEvent)
    assert (uploaded.paths, uploaded.ref) == (("a.txt",), "e1")


def test_other_facts_are_not_presented():
    assert StatusProjection().project(ConnectedEvent(owned_process=False)) is None
