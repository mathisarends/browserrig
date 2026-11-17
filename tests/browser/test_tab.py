import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cdpify import CDPCommandError
from cdpify.domains.runtime import EvaluateResult, ExceptionDetails, RemoteObject

from browserrig.browser import OpenDialog, Tab
from browserrig.browser import (  # smelt: ignore[SMT107] -- test seam
    # Shorten the viewport probe deadline at its owning module.
    tab as tab_module,
)
from browserrig.core import BrowserError, ViewportSize
from browserrig.events import CursorStateEvent, KeyPressedEvent


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            RemoteObject(type="object", value={"text": "Grüße", "count": 0}),
            '{"text": "Grüße", "count": 0}',
        ),
        (RemoteObject(type="boolean", value=False), "false"),
        (RemoteObject(type="object", subtype="null"), "null"),
        (RemoteObject(type="object", subtype="null", value=None), "null"),
        (RemoteObject(type="undefined"), "undefined"),
        (RemoteObject(type="number", unserializable_value="NaN"), "NaN"),
        (RemoteObject(type="number", unserializable_value="-0"), "-0"),
        (RemoteObject(type="bigint", unserializable_value="42n"), "42n"),
        (RemoteObject(type="symbol", description="Symbol(test)"), "Symbol(test)"),
    ],
)
async def test_runtime_evaluation_returns_javascript_values_and_releases_handles(
    value, expected
):
    tab, runtime = _tab(EvaluateResult(result=value))
    assert await tab.evaluate("expression", timeout_seconds=2) == expected
    arguments = runtime.evaluate.await_args.kwargs
    assert arguments["expression"] == "expression"
    assert arguments["return_by_value"] and arguments["await_promise"]
    assert arguments["repl_mode"] and arguments["user_gesture"]
    assert arguments["timeout"] == 2000
    assert "context_id" not in arguments
    runtime.release_object_group.assert_awaited_once_with(
        object_group=arguments["object_group"]
    )
    tab.layout_changed.assert_called_once()


async def test_javascript_exception_is_reported_without_retrying():
    exception = RemoteObject(
        type="object", subtype="error", description="Error: shell failed"
    )
    tab, runtime = _tab(
        EvaluateResult(
            result=exception,
            exception_details=ExceptionDetails(
                exception_id=1,
                text="Uncaught",
                line_number=0,
                column_number=0,
                exception=exception,
            ),
        )
    )
    with pytest.raises(BrowserError, match="JavaScript failed: Error: shell failed"):
        await tab.evaluate("expression")
    runtime.evaluate.assert_awaited_once()
    runtime.release_object_group.assert_awaited_once()
    tab.layout_changed.assert_called_once()


async def test_pending_javascript_has_a_deadline_and_releases_handles():
    tab, runtime = _tab(None)

    async def pending(**_kwargs):
        await asyncio.Event().wait()

    runtime.evaluate.side_effect = pending
    with pytest.raises(BrowserError, match="JavaScript timed out"):
        await tab.evaluate("expression", timeout_seconds=0.01)
    runtime.evaluate.assert_awaited_once()
    runtime.release_object_group.assert_awaited_once()
    tab.layout_changed.assert_called_once()


async def test_unserializable_result_is_reported_without_reexecuting_the_code():
    tab, runtime = _tab(None)
    runtime.evaluate.side_effect = CDPCommandError(
        "Runtime.evaluate", -32000, "Object couldn't be returned by value"
    )
    with pytest.raises(BrowserError, match="return JSON-serializable data"):
        await tab.evaluate("expression")
    runtime.evaluate.assert_awaited_once()
    runtime.release_object_group.assert_awaited_once()


async def test_coordinate_receipts_carry_the_viewport_measured_with_them():
    events = []
    tab, page = _emitting_tab(events)
    page.get_layout_metrics.side_effect = [_metrics(1280, 800), _metrics(640, 480)]
    await tab.emit(CursorStateEvent(x=10, y=20))
    await tab.emit(CursorStateEvent(x=10, y=20))
    await tab.emit(KeyPressedEvent(key="a"))
    assert [event.viewport for event in events[:2]] == [
        ViewportSize(width=1280, height=800),
        ViewportSize(width=640, height=480),
    ]
    assert not hasattr(events[2], "viewport")
    assert page.get_layout_metrics.await_count == 2


@pytest.mark.parametrize("failure", ["dialog", "error", "timeout"])
async def test_unmeasurable_viewport_keeps_the_last_known_size(monkeypatch, failure):
    monkeypatch.setattr(tab_module, "_VIEWPORT_PROBE_SECONDS", 0.01)
    events = []
    tab, page = _emitting_tab(events)
    page.get_layout_metrics.return_value = _metrics(1280, 800)
    await tab.emit(CursorStateEvent(x=10, y=20))

    async def pending():
        await asyncio.Event().wait()

    if failure == "dialog":
        tab.dialog = OpenDialog("alert", "Blocked")
    elif failure == "error":
        page.get_layout_metrics.side_effect = CDPCommandError(
            "Page.getLayoutMetrics", -32000, "Target closed"
        )
    else:
        page.get_layout_metrics.side_effect = pending
    await tab.emit(CursorStateEvent(x=30, y=40))
    assert events[-1].viewport == ViewportSize(width=1280, height=800)


def _emitting_tab(events):
    async def emit(event):
        events.append(event)

    page = SimpleNamespace(get_layout_metrics=AsyncMock())
    return Tab("tab", SimpleNamespace(page=page), emit=emit), page


def _metrics(width, height):
    return SimpleNamespace(
        css_layout_viewport=SimpleNamespace(client_width=width, client_height=height)
    )


def _tab(result):
    runtime = SimpleNamespace(
        evaluate=AsyncMock(return_value=result),
        release_object_group=AsyncMock(),
    )
    tab = Tab("tab", SimpleNamespace(runtime=runtime))
    tab.layout_changed = Mock()
    return tab, runtime
