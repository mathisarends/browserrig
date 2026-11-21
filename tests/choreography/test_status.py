import pytest

from browserrig.choreography import (
    Activity,
    ActivityPresentedEvent,
    Choreography,
    Download,
    DownloadPresentedEvent,
    FileTransfer,
    UploadPresentedEvent,
    Work,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.choreography.status import (  # smelt: ignore[ARC007] -- test seam
    # Test status projection independently of plugin activation.
    ProjectStatus,
)
from browserrig.core import ActivityKind, ActivityOutcome, FileSource
from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    ConnectedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FileOpenedEvent,
    FilesUploadedEvent,
)
from tests.fakes import mounted


def test_download_receipts_keep_the_filename_from_the_started_fact():
    status = ProjectStatus()
    started = status(
        DownloadStartedEvent(
            download_id="d", filename="a.pdf", url="https://x/", target_id="tab"
        )
    )
    progressed = status(
        DownloadProgressedEvent(download_id="d", received_bytes=10, total_bytes=20)
    )
    failed = status(DownloadFailedEvent(download_id="d", reason="x" * 400))
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
    status = ProjectStatus()
    started = status(
        ActivityStartedEvent(interval_id="i", kind=ActivityKind.HANDOFF, cause_id="c")
    )
    finished = status(
        ActivityFinishedEvent(
            interval_id="i",
            kind=ActivityKind.HANDOFF,
            cause_id="c",
            started_at=0,
            outcome=ActivityOutcome.COMPLETED,
        )
    )
    uploaded = status(FilesUploadedEvent(paths=("a.txt",), ref="e1"))
    assert isinstance(started, ActivityPresentedEvent) and started.active
    assert isinstance(finished, ActivityPresentedEvent) and not finished.active
    assert isinstance(uploaded, UploadPresentedEvent)
    assert (uploaded.paths, uploaded.ref) == (("a.txt",), "e1")


def test_other_facts_are_not_presented():
    assert ProjectStatus()(ConnectedEvent(owned_process=False)) is None


@pytest.mark.parametrize(
    "selection,expected",
    [
        ((), []),
        ((Activity(),), [ActivityPresentedEvent]),
        ((FileTransfer(),), [UploadPresentedEvent]),
        ((Download(),), [DownloadPresentedEvent, DownloadPresentedEvent]),
        ((Work(),), [WorkPresentedEvent]),
    ],
)
async def test_only_selected_status_and_work_are_published(selection, expected):
    async with mounted(Choreography(only=selection)) as (services, scope):
        await scope.dispatch(
            DownloadStartedEvent(download_id="d", filename="a.pdf", url="https://x/")
        )
        await scope.dispatch(DownloadProgressedEvent(download_id="d", received_bytes=1))
        await scope.dispatch(
            ActivityStartedEvent(
                interval_id="i", kind=ActivityKind.HANDOFF, cause_id="c"
            )
        )
        await scope.dispatch(FilesUploadedEvent(paths=("a.pdf",), ref="e1"))
        await scope.dispatch(FileOpenedEvent(path="a.pdf", source=FileSource.WORKSPACE))
        assert [type(event) for event in services.events] == expected
