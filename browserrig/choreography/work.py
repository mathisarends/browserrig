"""Project typed browser tool results into bounded presentation receipts."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from harnessed import ToolCall, ToolResult, ToolStatus
from pydantic import TypeAdapter, ValidationError

from browserrig.browser import TabInfo
from browserrig.core import ActionKind, Region
from browserrig.files import Download, FileContent, FileEntry, FileListing

from .events import CaptureRegion, WorkPhase, WorkPresentedEvent

# Native input already explains other operations. Their failures still get a receipt.
SILENT_WORK = {
    ActionKind.READ_FILE: "Reading file",
    ActionKind.SEARCH_PAGE: "Searching page",
    ActionKind.WRITE_FILE: "Saving file",
    ActionKind.EDIT_FILE: "Editing file",
    ActionKind.LIST_FILES: "Listing files",
    ActionKind.LIST_DOWNLOADS: "Listing downloads",
    ActionKind.LIST_TABS: "Listing tabs",
    ActionKind.JAVASCRIPT: "Executing JavaScript",
    ActionKind.SCREENSHOT: "Capturing screenshot",
    ActionKind.GO_BACK: "Going back",
    ActionKind.GO_FORWARD: "Going forward",
    ActionKind.RELOAD: "Reloading page",
    ActionKind.SELECT: "Selecting option",
    ActionKind.SELECT_OPTIONS: "Selecting options",
    ActionKind.SET_DATE: "Setting date / time",
    ActionKind.HANDLE_DIALOG: "Handling dialog",
}
_PREVIEW_CHARS = 1800
_TABS = TypeAdapter(list[TabInfo])
_DOWNLOADS = TypeAdapter(list[Download])


def started(call: ToolCall, kind: ActionKind) -> WorkPresentedEvent:
    args = call.arguments
    detail = _selection(args)
    preview = ""
    region = None
    match kind:
        case ActionKind.SEARCH_PAGE:
            queries = [args.get("query"), *(args.get("alternatives") or ())]
            detail = " | ".join(f'"{query}"' for query in queries if query)
        case ActionKind.JAVASCRIPT:
            preview = clipped(str(args.get("code", "")))
        case ActionKind.WRITE_FILE | ActionKind.EDIT_FILE:
            preview, change = _file_change(kind, args)
            detail += f" · {change}"
        case ActionKind.SCREENSHOT:
            value = args.get("region")
            # Invalid tool arguments must reach ordinary tool validation, not break presentation.
            try:
                area = Region.model_validate(value) if value is not None else None
                region = (
                    CaptureRegion(area.x, area.y, area.width, area.height)
                    if area
                    else None
                )
            except ValidationError:
                region = None
            detail = "Viewport" if region is None else "Selected viewport region"
        case ActionKind.SELECT | ActionKind.SET_DATE:
            # The element highlight shows where; the caption names the value.
            detail = str(args.get("value", ""))
        case ActionKind.SELECT_OPTIONS:
            values = args.get("values")
            if isinstance(values, list):
                detail = ", ".join(str(value)[:100] for value in values[:10])
                if not values:
                    detail = "Empty selection"
        case ActionKind.HANDLE_DIALOG:
            detail = "Accepting dialog" if args.get("accept") else "Dismissing dialog"
    return WorkPresentedEvent(
        work_id=f"tool:{call.id}",
        call_id=call.id,
        tool_name=call.name,
        kind=kind,
        title=SILENT_WORK.get(kind, kind.value.replace("_", " ").capitalize()),
        phase=WorkPhase.RUNNING,
        source_path=str(args.get("path", "")),
        detail=clipped(detail, 300),
        preview=preview,
        region=region,
    )


def finished(
    receipt: WorkPresentedEvent,
    result: ToolResult,
    *,
    elapsed: float,
) -> WorkPresentedEvent:
    phase = WorkPhase.COMPLETED
    if result.status is ToolStatus.CANCELLED:
        phase = WorkPhase.CANCELLED
    elif result.is_error:
        phase = WorkPhase.FAILED
    event = replace(receipt, phase=phase, elapsed=elapsed)
    if result.is_error:
        return replace(event, detail=result.status.value, preview=clipped(result.text))
    try:
        return _result(event, result)
    except ValidationError:
        # Custom tool-result hooks may deliberately replace the standard DTO.
        return replace(event, preview=clipped(result.text))


def clipped(text: str, limit: int = _PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n… Preview shortened"


def _result(event: WorkPresentedEvent, result: ToolResult) -> WorkPresentedEvent:
    match event.kind:
        case ActionKind.READ_FILE:
            event = _file(event, FileContent.model_validate_json(result.text))
        case ActionKind.WRITE_FILE | ActionKind.EDIT_FILE:
            entry = FileEntry.model_validate_json(result.text)
            event = replace(
                event,
                detail=f"{entry.path} · {entry.size or 0:,} bytes saved",
                artifact_path=entry.path,
            )
        case ActionKind.LIST_FILES | ActionKind.LIST_TABS | ActionKind.LIST_DOWNLOADS:
            event = _listing(event, result)
        case ActionKind.SEARCH_PAGE:
            # The first line counts the records; the rest is what the model reads.
            summary, _, records = result.text.partition("\n")
            event = replace(
                event,
                detail=clipped(summary, 300),
                preview=clipped(records.strip()),
            )
        case ActionKind.SCREENSHOT:
            event = replace(
                event,
                phase=WorkPhase.RUNNING,
                detail="Requested · waiting for the next observation",
            )
        case ActionKind.JAVASCRIPT:
            # The overlay shows the returned value; the preview keeps the full result.
            value = result.text.removeprefix("JavaScript result:\n")
            event = replace(
                event, detail=clipped(value, 300), preview=clipped(result.text)
            )
        case _:
            event = replace(event, preview=clipped(result.text))
    return event


def _listing(event: WorkPresentedEvent, result: ToolResult) -> WorkPresentedEvent:
    match event.kind:
        case ActionKind.LIST_FILES:
            listing = FileListing.model_validate_json(result.text)
            detail = f"{listing.directory} · {len(listing.entries)} entries"
            if listing.next_offset is not None:
                detail += f" · continues at {listing.next_offset}"
            preview = "\n".join(
                entry.path + ("/" if entry.is_directory else "")
                for entry in listing.entries[:10]
            )
            return replace(event, detail=detail, preview=clipped(preview))
        case ActionKind.LIST_TABS:
            tabs = _TABS.validate_json(result.text)
            return replace(
                event,
                detail=f"{len(tabs)} tabs",
                preview=clipped(
                    "\n".join(f"{tab.title} · {tab.url}" for tab in tabs[:8])
                ),
            )
        case ActionKind.LIST_DOWNLOADS:
            downloads = _DOWNLOADS.validate_json(result.text)
            return replace(
                event,
                detail=f"{len(downloads)} downloads",
                preview=clipped(
                    "\n".join(
                        f"{item.filename} · {item.state.value} · {item.path or item.url}"
                        for item in downloads[:8]
                    )
                ),
            )
    raise ValueError(f"Not a listing tool: {event.kind}")


def _file(event: WorkPresentedEvent, content: FileContent) -> WorkPresentedEvent:
    detail = content.path
    if content.sheet:
        detail += f" · {content.sheet}"
    if content.cell_range:
        detail += f" · {content.cell_range}"
    if content.member:
        detail += f" · {content.member}"
    if content.page_number is not None:
        detail += f" · page {content.page_number}"
        if content.page_count is not None:
            detail += f" / {content.page_count}"
    detail += (
        f" · {content.format} · {len(content.text):,} characters · {content.status}"
    )
    if content.next_offset is not None:
        detail += f" · continues at {content.next_offset}"
    return replace(
        event,
        phase=WorkPhase.WARNING
        if content.status != "complete" or content.limitations
        else WorkPhase.COMPLETED,
        detail=clipped(detail, 500),
        preview=clipped(content.text),
        limitations=_limitations(content.limitations),
        artifact_path=content.extracted_path or "",
        source_path=content.path,
        characters=len(content.text),
        offset=content.offset,
        next_offset=content.next_offset,
        page_number=content.page_number,
        page_count=content.page_count,
        content_status=content.status,
    )


def _limitations(items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(clipped(item, 240) for item in items[:6])


def _file_change(kind: ActionKind, args: Mapping[str, Any]) -> tuple[str, str]:
    """The text being saved and how it changes the file."""
    if kind is ActionKind.EDIT_FILE:
        change = (
            "replacing every match"
            if args.get("replace_all")
            else "replacing one match"
        )
        return clipped(str(args.get("new_text", ""))), change
    if args.get("append"):
        change = "appending to file"
    elif args.get("overwrite"):
        change = "replacing existing file if present"
    else:
        change = "creating file"
    return clipped(str(args.get("content", ""))), change


def _selection(args: Mapping[str, Any]) -> str:
    parts = [
        str(args[key])
        for key in ("path", "sheet", "cell_range", "member")
        if args.get(key)
    ]
    if args.get("page_number") is not None:
        parts.append(f"page {args['page_number']}")
    if args.get("ocr") is True:
        parts.append("OCR requested")
    return " · ".join(parts)
