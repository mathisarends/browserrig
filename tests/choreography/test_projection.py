from browserrig.choreography import WorkPhase
from browserrig.choreography.projection import (  # smelt: ignore[ARC007] -- test seam
    # Test event projection independently of plugin activation.
    project,
)
from browserrig.core import ActionKind, ReadinessPhase
from browserrig.events import (
    ActionFailedEvent,
    FileReadFailedEvent,
    FileReadStartedEvent,
    ReadyEvent,
)


def test_file_read_presentation_preserves_source_and_selectors():
    receipt = project(
        FileReadStartedEvent(
            read_id="read-1",
            path="book.xlsx",
            sheet="Revenue",
            cell_range="A2:C8",
            target_id="tab-1",
            document_id="doc-1",
        )
    )
    assert receipt is not None and receipt.kind is ActionKind.READ_FILE
    assert receipt.phase is WorkPhase.RUNNING
    assert "Revenue" in receipt.detail and "A2:C8" in receipt.detail
    assert receipt.target_id == "tab-1" and receipt.document_id == "doc-1"


def test_page_readiness_is_not_presented():
    assert (
        project(
            ReadyEvent(
                readiness_id="ready-1",
                phase=ReadinessPhase.ACTION,
                duration_seconds=0.05,
            )
        )
        is None
    )


def test_read_cancellation_uses_typed_outcome_not_reason_text():
    receipt = project(
        FileReadFailedEvent(
            read_id="read", path="scan.pdf", reason="Stopped", cancelled=True
        )
    )
    assert receipt is not None and receipt.phase is WorkPhase.CANCELLED


def test_cancelled_action_receipt_keeps_its_call_identity():
    receipt = project(
        ActionFailedEvent(
            action_id="action-1",
            kind=ActionKind.CLICK,
            dispatched=True,
            reason="cancelled",
            cancelled=True,
            call_id="call-1",
            label="click",
        )
    )
    assert receipt is not None and receipt.phase is WorkPhase.CANCELLED
    assert receipt.action_id == "action-1" and receipt.call_id == "call-1"
