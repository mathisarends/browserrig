"""Project durable facts once for both the browser and remote renderers."""

from dataclasses import replace

from browserrig.core import ActionKind, HandoffStatus
from browserrig.events import (
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    BrowserEvent,
    DialogHandledEvent,
    DialogOpenedEvent,
    FileOpenedEvent,
    FileReadFailedEvent,
    FileReadFinishedEvent,
    FileReadStartedEvent,
    FilesListedEvent,
    FileWrittenEvent,
    HandoffFinishedEvent,
    HandoffRequestedEvent,
)

from .events import WorkPhase, WorkPresentedEvent
from .work import SILENT_WORK, clipped


def project(event: BrowserEvent) -> WorkPresentedEvent | None:
    """Return presentation data without changing the authoritative fact event."""
    receipt = _project(event)
    return (
        replace(receipt, target_id=event.target_id, document_id=event.document_id)
        if receipt
        else None
    )


def _project(event: BrowserEvent) -> WorkPresentedEvent | None:
    match event:
        case FileReadStartedEvent() | FileReadFinishedEvent() | FileReadFailedEvent():
            receipt = _read(event)
        case FileWrittenEvent() | FilesListedEvent() | FileOpenedEvent():
            receipt = _files(event)
        case ActionStartedEvent() | ActionFinishedEvent() | ActionFailedEvent():
            receipt = _action(event)
        case DialogOpenedEvent() | DialogHandledEvent():
            receipt = _dialog(event)
        case HandoffRequestedEvent() | HandoffFinishedEvent():
            receipt = _handoff(event)
        case _:
            receipt = None
    return receipt


def _read(
    event: FileReadStartedEvent | FileReadFinishedEvent | FileReadFailedEvent,
) -> WorkPresentedEvent | None:
    match event:
        case FileReadStartedEvent():
            parts = [
                event.path,
                event.sheet,
                event.cell_range,
                event.member,
                f"page {event.page_number}" if event.page_number else None,
                "OCR requested" if event.ocr else None,
            ]
            return WorkPresentedEvent(
                work_id=f"read:{event.read_id}",
                kind=ActionKind.READ_FILE,
                title="Reading file",
                phase=WorkPhase.RUNNING,
                detail=" · ".join(part for part in parts if part),
                source_path=event.path,
                page_number=event.page_number,
                offset=event.offset,
            )
        case FileReadFinishedEvent():
            detail = (
                f"{event.path} · {event.format} · "
                f"{event.characters:,} characters · {event.status}"
            )
            if event.page_count:
                detail += f" · page {event.page_number} / {event.page_count}"
            if event.next_offset is not None:
                detail += f" · continues at {event.next_offset}"
            return WorkPresentedEvent(
                work_id=f"read:{event.read_id}",
                kind=ActionKind.READ_FILE,
                title="File read",
                phase=WorkPhase.COMPLETED
                if event.status == "complete"
                else WorkPhase.WARNING,
                detail=detail,
                source_path=event.path,
                characters=event.characters,
                offset=event.offset,
                next_offset=event.next_offset,
                page_number=event.page_number,
                page_count=event.page_count,
            )
        case FileReadFailedEvent():
            return WorkPresentedEvent(
                work_id=f"read:{event.read_id}",
                kind=ActionKind.READ_FILE,
                title="File read cancelled" if event.cancelled else "File read failed",
                phase=WorkPhase.CANCELLED if event.cancelled else WorkPhase.FAILED,
                detail=event.path,
                preview=clipped(event.reason),
                source_path=event.path,
            )


def _files(
    event: FileWrittenEvent | FilesListedEvent | FileOpenedEvent,
) -> WorkPresentedEvent | None:
    match event:
        case FileWrittenEvent():
            return WorkPresentedEvent(
                work_id=f"write:{event.path}",
                kind=ActionKind.WRITE_FILE,
                title="File created" if event.created else "File updated",
                phase=WorkPhase.COMPLETED,
                detail=f"{event.path} · {event.size:,} bytes",
                artifact_path=event.path,
            )
        case FilesListedEvent():
            detail = f"{event.directory} · {event.entries} entries"
            if event.next_offset is not None:
                detail += f" · continues at {event.next_offset}"
            return WorkPresentedEvent(
                work_id=f"list:{event.directory}",
                kind=ActionKind.LIST_FILES,
                title="Files listed",
                phase=WorkPhase.COMPLETED,
                detail=detail,
            )
        case FileOpenedEvent():
            return WorkPresentedEvent(
                work_id=f"open:{event.path}",
                kind=ActionKind.OPEN_FILE,
                title="File opened",
                phase=WorkPhase.COMPLETED,
                detail=event.path,
            )


def _dialog(event: DialogOpenedEvent | DialogHandledEvent) -> WorkPresentedEvent | None:
    match event:
        case DialogOpenedEvent():
            return WorkPresentedEvent(
                work_id=f"dialog:{event.target_id}",
                kind=ActionKind.HANDLE_DIALOG,
                title=f"{event.kind.capitalize()} dialog",
                phase=WorkPhase.RUNNING,
                detail=clipped(event.message, 300),
            )
        case DialogHandledEvent():
            return WorkPresentedEvent(
                work_id=f"dialog:{event.target_id}",
                kind=ActionKind.HANDLE_DIALOG,
                title="Dialog handled",
                phase=WorkPhase.COMPLETED,
                detail="Accepted" if event.accepted else "Dismissed",
            )


def _handoff(
    event: HandoffRequestedEvent | HandoffFinishedEvent,
) -> WorkPresentedEvent | None:
    match event:
        case HandoffRequestedEvent():
            return WorkPresentedEvent(
                work_id=f"handoff:{event.handoff_id}",
                kind=ActionKind.WAIT,
                title="Human input requested",
                phase=WorkPhase.RUNNING,
                detail=clipped(event.reason, 300),
            )
        case HandoffFinishedEvent():
            return WorkPresentedEvent(
                work_id=f"handoff:{event.handoff_id}",
                kind=ActionKind.WAIT,
                title="Human input",
                phase=WorkPhase.COMPLETED
                if event.status in {HandoffStatus.DONE, HandoffStatus.RESUMED}
                else WorkPhase.WARNING,
                detail=event.status.value,
            )


def _action(
    event: ActionStartedEvent | ActionFinishedEvent | ActionFailedEvent,
) -> WorkPresentedEvent | None:
    phase = (
        WorkPhase.RUNNING
        if isinstance(event, ActionStartedEvent)
        else WorkPhase.COMPLETED
    )
    preview = ""
    if isinstance(event, ActionFailedEvent):
        phase = WorkPhase.CANCELLED if event.cancelled else WorkPhase.FAILED
        preview = clipped(event.reason)
    elif event.kind not in SILENT_WORK:
        return None
    return WorkPresentedEvent(
        work_id=f"action:{event.action_id}",
        kind=event.kind,
        action_id=event.action_id,
        title=SILENT_WORK.get(
            event.kind, event.kind.value.replace("_", " ").capitalize()
        ),
        phase=phase,
        preview=preview,
    )
