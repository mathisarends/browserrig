from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolError

from browserrig import FileSystem, LocalWorkspace, MountedWorkspace
from browserrig.browser import Tab
from browserrig.core import Bounds, BrowserError, ElementPoint, Point
from browserrig.events import (
    ActionFailedEvent,
    ActionFinishedEvent,
    FilesUploadedEvent,
    PageState,
)
from browserrig.input import Instant
from browserrig.kinds import ActionKind, ReadinessPhase
from browserrig.tools import Actions, FileTools
from browserrig.tools.effects import Effect
from tests.fakes import FakeServices, mounted


@pytest.mark.parametrize(
    "error", [BrowserError("wrong input"), ToolError("denied"), ValueError("bad")]
)
async def test_action_keeps_error_details_and_uncertain_dispatch(error):
    async with mounted(Actions()) as (services, ctx):
        with pytest.raises(ToolError, match=str(error)) as caught:
            await ctx[Actions].run(
                kind=ActionKind.TYPE, operation=AsyncMock(side_effect=error)
            )
    assert "may have run" in str(caught.value)
    receipt = _first(services.events, ActionFailedEvent)
    assert receipt.dispatched and str(error) in receipt.reason


async def test_validation_rejects_before_dispatch():
    operation = AsyncMock()
    async with mounted(Actions()) as (services, ctx):
        with pytest.raises(ToolError, match="wrong input") as caught:
            await ctx[Actions].run(
                kind=ActionKind.UPLOAD,
                check=AsyncMock(side_effect=BrowserError("wrong input")),
                operation=operation,
            )
    assert "may have run" not in str(caught.value)
    operation.assert_not_awaited()
    assert len(services.events) == 1
    assert not _first(services.events, ActionFailedEvent).dispatched


@pytest.mark.parametrize(
    "selection", ["outside", "missing", "directory", "no_workspace"]
)
async def test_upload_rejects_invalid_selection_before_any_browser_input(
    tmp_path, selection
):
    files = FileSystem(LocalWorkspace(tmp_path / "workspace"))
    await files.initialize()
    saved = await files.write_file("report.txt", "report")
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    invalid = {"outside": str(secret), "missing": "missing.txt", "directory": "."}
    paths = [saved.path, invalid.get(selection, saved.path)]
    async with _uploads(None if selection == "no_workspace" else files) as upload:
        with pytest.raises(ToolError):
            await upload.tools.upload_files("input", paths, actions=upload.actions)
    upload.actions.element_point.assert_not_awaited()
    upload.handle.upload_files.assert_not_awaited()
    assert len(upload.services.events) == 1
    assert not _first(upload.services.events, ActionFailedEvent).dispatched


async def test_upload_sends_only_resolved_workspace_paths_to_chrome(tmp_path):
    files = FileSystem(LocalWorkspace(tmp_path / "workspace"))
    await files.initialize()
    saved = await files.write_file("report.txt", "report")
    async with _uploads(files) as upload:
        result = await upload.tools.upload_files(
            "input", ["report.txt"], actions=upload.actions
        )
    assert result.text == "Files assigned to input."
    # Chrome reads the file on its own host; events keep the workspace path.
    upload.handle.upload_files.assert_awaited_once_with(
        [str(files.workspace.directory / "report.txt")]
    )
    upload.actions.element_point.assert_awaited_once()
    assert upload.services.browser.mouse.position == Point(x=40, y=30)
    uploaded = _first(upload.services.events, FilesUploadedEvent)
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
    async with mounted(Actions()) as (services, ctx):
        tab = services.browser.active_tab
        tab.dialog = ("alert", "hello")
        await ctx[Actions].run(
            kind=kind, operation=AsyncMock(return_value=Effect("Done.")), settle=False
        )
    finished = _first(services.events, ActionFinishedEvent)
    assert finished.before == PageState(url=tab.url, document_id=tab.document_id)
    assert not services.readiness.phases


@pytest.mark.parametrize("kind", [ActionKind.PRESS, ActionKind.MOVE_MOUSE])
async def test_input_rejects_a_document_changed_between_calls(kind):
    operation = AsyncMock()
    async with mounted(Actions()) as (services, ctx):
        tab = services.browser.active_tab
        services.observe.snapshot = SimpleNamespace(tab_id=tab.id, document_id="old")
        with pytest.raises(ToolError, match="act on the next observation"):
            await ctx[Actions].run(kind=kind, operation=operation)
    operation.assert_not_awaited()
    assert not _first(services.events, ActionFailedEvent).dispatched


async def test_navigation_does_not_wait_for_the_current_dom_to_stop_changing():
    async with mounted(Actions()) as (services, ctx):
        await ctx[Actions].run(
            kind=ActionKind.NAVIGATE,
            operation=AsyncMock(return_value=Effect("Navigated.")),
        )
    # The only wait is the one that dispatches the navigation.
    assert services.readiness.phases == [ReadinessPhase.NAVIGATION]


def _first(events, kind):
    return next(event for event in events if isinstance(event, kind))


class _Aiming(Instant):
    """Aims somewhere new each time it is asked, and remembers the target sizes."""

    def __init__(self, *aims: tuple[float, float]) -> None:
        self._aims = list(aims)
        self.sizes: list[tuple[float, float]] = []

    def aim_fractions(
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        self.sizes.append((target_width, target_height))
        return self._aims.pop(0)


async def test_an_action_aims_once_at_each_target():
    motor = _Aiming((0.2, 0.3), (0.7, 0.6))
    aims = []

    async def locate(*, aim):
        aims.append(aim)
        return ElementPoint(x=1, y=1)

    async with mounted(Actions()) as (services, ctx):
        services.browser.input.pace(motor)
        bounds = Bounds(x=0, y=0, width=80, height=20)
        services.observe.element = AsyncMock(
            return_value=SimpleNamespace(
                element=SimpleNamespace(bounds=bounds), locate=locate
            )
        )
        tab = services.browser.active_tab
        with services.browser.input.action("first"):
            await ctx[Actions].element_point(tab=tab, ref="e1", scroll=False)
            # The re-check after hover resolves the same spot.
            await ctx[Actions].element_point(tab=tab, ref="e1", scroll=False)
        with services.browser.input.action("second"):
            await ctx[Actions].element_point(tab=tab, ref="e1", scroll=False)
    assert aims == [(0.2, 0.3), (0.2, 0.3), (0.7, 0.6)]
    assert motor.sizes == [(80, 20), (80, 20)]


class _FileTools(FileTools, provides=True):
    """Expose the mounted plugin, so tests can call its tool directly."""


class _Upload(NamedTuple):
    services: FakeServices
    actions: Actions
    tools: FileTools
    handle: SimpleNamespace


@asynccontextmanager
async def _uploads(files):
    plugins = (Actions(), _FileTools())
    bridge = MountedWorkspace()
    async with mounted(*plugins, bridge=bridge, files=files) as (services, ctx):
        cdp = SimpleNamespace(input=SimpleNamespace(dispatch_mouse_event=AsyncMock()))
        services.browser.active_tab = Tab("tab", cdp, emit=services.record)
        handle = SimpleNamespace(
            element=SimpleNamespace(input_type="file"), upload_files=AsyncMock()
        )
        services.observe.element = AsyncMock(return_value=handle)
        actions = ctx[Actions]
        actions.element_point = AsyncMock(return_value=ElementPoint(x=40, y=30))
        yield _Upload(services, actions, ctx[_FileTools], handle)
