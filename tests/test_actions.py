# Internal transaction state is inspected to verify failure receipts.
# pylint: disable=protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolError

from browserrig import FileSystem, FileSystemOptions
from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import ElementPoint
from browserrig.events import (
    ActionFailedEvent,
    CursorMovedEvent,
    FilesUploadedEvent,
    FileTransferEvent,
)
from browserrig.input import Input
from browserrig.input import controller as controller_module
from browserrig.input import mouse as mouse_module
from browserrig.kinds import ActionKind, FileTransferDirection
from browserrig.tools.execution import Actions
from browserrig.tools.files import UploadTools


@pytest.mark.parametrize(
    "error", [BrowserError("wrong input"), ToolError("denied"), ValueError("bad")]
)
async def test_action_keeps_error_details_and_uncertain_dispatch(error):
    actions, events = _actions()
    with pytest.raises(ToolError, match=str(error)) as caught:
        await Actions.run(
            actions, kind=ActionKind.TYPE, operation=AsyncMock(side_effect=error)
        )
    assert "may have run" in str(caught.value)
    receipt = next(event for event in events if isinstance(event, ActionFailedEvent))
    assert receipt.dispatched and str(error) in receipt.reason


async def test_validation_rejects_before_dispatch():
    actions, events = _actions()
    operation = AsyncMock()
    with pytest.raises(ToolError, match="wrong input") as caught:
        await Actions.run(
            actions,
            kind=ActionKind.UPLOAD,
            check=AsyncMock(side_effect=BrowserError("wrong input")),
            operation=operation,
        )
    assert "may have run" not in str(caught.value)
    operation.assert_not_awaited()
    assert len(events) == 1
    assert isinstance(events[0], ActionFailedEvent) and not events[0].dispatched


@pytest.mark.parametrize(
    "selection", ["outside", "missing", "directory", "no_workspace"]
)
async def test_upload_rejects_invalid_selection_before_any_browser_input(
    tmp_path, selection
):
    files = FileSystem(FileSystemOptions(directory=tmp_path / "workspace"))
    files.initialize()
    saved = files.write_file("report.txt", "report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    invalid = {"outside": str(secret), "missing": "missing.txt", "directory": "."}
    paths = [saved.path, invalid.get(selection, saved.path)]
    tools, actions, handle, events = _uploads(
        None if selection == "no_workspace" else files
    )
    with pytest.raises(ToolError):
        await UploadTools.upload_files(tools, "input", paths, actions=actions)
    actions.element_point.assert_not_awaited()
    handle.upload_files.assert_not_awaited()
    assert len(events) == 1
    assert isinstance(events[0], ActionFailedEvent) and not events[0].dispatched


async def test_upload_sends_only_resolved_workspace_paths_to_chrome(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(controller_module.asyncio, "sleep", AsyncMock())
    files = FileSystem(FileSystemOptions(directory=tmp_path / "workspace"))
    files.initialize()
    saved = files.write_file("report.txt", "report")
    tools, actions, handle, events = _uploads(files)
    result = await UploadTools.upload_files(
        tools, "input", ["report.txt"], actions=actions
    )
    assert result.text == "Files assigned to input."
    handle.upload_files.assert_awaited_once_with([saved.path])
    actions.element_point.assert_awaited_once()
    moved, transfer, uploaded = (
        next(event for event in events if isinstance(event, kind))
        for kind in (CursorMovedEvent, FileTransferEvent, FilesUploadedEvent)
    )
    assert moved.to_position == (40, 30)
    assert transfer.direction == FileTransferDirection.UPLOAD
    assert transfer.paths == (saved.path,) and (transfer.x, transfer.y) == (40, 30)
    assert events.index(moved) < events.index(transfer) < events.index(uploaded)
    assert uploaded.paths == (saved.path,) and uploaded.ref == "input"
    assert uploaded.target_id == "tab"


@pytest.mark.parametrize(
    "kind",
    [
        ActionKind.TAB,
        ActionKind.OPEN_TAB,
        ActionKind.SWITCH_TAB,
        ActionKind.CLOSE_TAB,
        ActionKind.OPEN_FILE,
        ActionKind.OPEN_DOWNLOADED_FILE,
    ],
)
async def test_tab_management_does_not_wait_on_current_page_dialog(kind):
    tab = SimpleNamespace(
        url="about:blank", document_id="doc", dialog=("alert", "hello")
    )
    before = await Actions._prepare(SimpleNamespace(), tab, kind)
    assert before.url == tab.url and before.document_id == tab.document_id


@pytest.mark.parametrize("kind", [ActionKind.PRESS, ActionKind.MOVE_MOUSE])
async def test_input_rejects_a_document_changed_between_calls(kind):
    tab = SimpleNamespace(
        id="tab",
        document_id="new-doc",
        sync_document=AsyncMock(),
    )
    actions = SimpleNamespace(
        readiness=SimpleNamespace(
            wait=AsyncMock(
                return_value=SimpleNamespace(status="ready", timed_out=False)
            )
        ),
        observe=SimpleNamespace(
            snapshot=SimpleNamespace(
                tab_id="tab",
                document_id="old-doc",
            )
        ),
    )
    with pytest.raises(BrowserError, match="act on the next observation"):
        await Actions._prepare(actions, tab, kind)


async def test_navigation_does_not_wait_for_the_current_dom_to_stop_changing():
    tab = SimpleNamespace(
        id="tab", url="https://example.org", document_id="doc", dialog=None
    )
    actions = SimpleNamespace(readiness=SimpleNamespace(wait=AsyncMock()))
    before = await Actions._prepare(actions, tab, ActionKind.NAVIGATE)
    assert before.url == tab.url
    actions.readiness.wait.assert_not_awaited()


def _actions():
    events = []

    async def emit(event):
        events.append(event)

    cdp = SimpleNamespace(input=SimpleNamespace(dispatch_mouse_event=AsyncMock()))
    tab = Tab("tab", cdp, emit=emit)
    actions = SimpleNamespace(
        browser=SimpleNamespace(
            action_lock=asyncio.Lock(), active_tab=tab, input=Input(lambda: tab)
        ),
        _events=SimpleNamespace(emit=AsyncMock(side_effect=events.append)),
        _prepare=AsyncMock(return_value=SimpleNamespace()),
    )
    actions._fail = lambda *args: Actions._fail(actions, *args)
    return actions, events


def _uploads(files):
    actions, events = _actions()
    actions.run = lambda **kwargs: Actions.run(actions, **kwargs)
    actions.element_point = AsyncMock(return_value=ElementPoint(x=40, y=30))
    actions._settle = AsyncMock(return_value="")
    handle = SimpleNamespace(
        element=SimpleNamespace(input_type="file"), upload_files=AsyncMock()
    )
    tools = SimpleNamespace(
        _browser=SimpleNamespace(
            files=files, mouse=actions.browser.input.mouse, input=actions.browser.input
        ),
        _events=SimpleNamespace(emit=AsyncMock(side_effect=events.append)),
        _observe=SimpleNamespace(element=AsyncMock(return_value=handle)),
    )
    return tools, actions, handle, events
