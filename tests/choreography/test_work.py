from harnessed import ToolCall, ToolResult, ToolStatus

from browserrig.choreography import WorkPhase
from browserrig.choreography.work import finished, started
from browserrig.core import ActionKind
from browserrig.files import FileContent
from browserrig.observation import ExtractedContent


def test_file_receipt_distinguishes_response_pagination_from_saved_extraction():
    content = FileContent(
        path="report.pdf",
        media_type="application/pdf",
        text="A" * 3000,
        format="pdf",
        page_number=2,
        page_count=18,
        next_offset=3000,
        status="partial",
        limitations=("Image text uses OCR",),
        extracted_path=".content/report.md",
    )
    receipt = finished(
        started(
            ToolCall("read_file", {"path": content.path, "page_number": 2}),
            ActionKind.READ_FILE,
        ),
        ToolResult(content.model_dump_json()),
        elapsed=1.2,
    )
    assert receipt.phase is WorkPhase.WARNING
    assert "page 2 / 18" in receipt.detail and "continues at 3000" in receipt.detail
    assert len(receipt.preview) < len(content.text)
    assert receipt.artifact_path == content.extracted_path
    assert receipt.limitations == content.limitations and receipt.elapsed == 1.2


def test_extraction_uses_typed_source_instead_of_parsing_markdown():
    extraction = ExtractedContent(
        url="https://example.org/article",
        title="Source title",
        markdown="# Content\n\nSome text",
        offset=100,
        next_offset=125,
        partial=True,
        limitations=("Embedded frame is unavailable",),
    )
    receipt = finished(
        started(
            ToolCall("extract_content", {"offset": 100}), ActionKind.EXTRACT_CONTENT
        ),
        ToolResult("A result review may change this text."),
        elapsed=0.3,
        extraction=extraction,
    )
    assert receipt.title == extraction.title and receipt.preview == extraction.markdown
    assert extraction.url in receipt.detail and "125" in receipt.detail
    assert receipt.phase is WorkPhase.WARNING and not receipt.artifact_path


def test_screenshot_request_is_not_a_completed_capture():
    receipt = started(
        ToolCall(
            "screenshot", {"region": {"x": 10, "y": 20, "width": 100, "height": 80}}
        ),
        ActionKind.SCREENSHOT,
    )
    pending = finished(receipt, ToolResult("Screenshot requested"), elapsed=0.01)
    assert pending.phase is WorkPhase.RUNNING and not pending.image_url
    assert pending.region == receipt.region and pending.region.x == 10


def test_tool_cancellation_keeps_identity_and_closes_the_receipt():
    call = ToolCall("execute_javascript", {"code": "await work()"})
    receipt = started(call, ActionKind.JAVASCRIPT)
    stopped = finished(
        receipt, ToolResult("Cancelled", ToolStatus.CANCELLED), elapsed=0.5
    )
    assert stopped.work_id == receipt.work_id and stopped.call_id == call.id
    assert stopped.phase is WorkPhase.CANCELLED and stopped.preview == "Cancelled"


def test_javascript_receipt_shows_code_then_returned_value():
    receipt = started(
        ToolCall("execute_javascript", {"code": "({answer: 42})"}),
        ActionKind.JAVASCRIPT,
    )
    assert receipt.preview == "({answer: 42})" and not receipt.detail
    done = finished(
        receipt, ToolResult('JavaScript result:\n{"answer": 42}'), elapsed=0.01
    )
    assert done.phase is WorkPhase.COMPLETED
    assert done.detail == '{"answer": 42}'
    assert done.preview == 'JavaScript result:\n{"answer": 42}'


def test_custom_result_does_not_break_successful_file_tool():
    receipt = finished(
        started(ToolCall("list_files", {}), ActionKind.LIST_FILES),
        ToolResult("Custom human-readable output"),
        elapsed=0,
    )
    assert receipt.phase is WorkPhase.COMPLETED
    assert receipt.preview == "Custom human-readable output"
