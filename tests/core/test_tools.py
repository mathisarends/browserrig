import pytest

from browserrig.core import ActionKind, browser_tool


def test_browser_tool_rejects_synchronous_callbacks_at_declaration_time():
    def click() -> str:
        raise AssertionError("Rejected callbacks must never execute")

    with pytest.raises(TypeError, match="requires an async function"):
        browser_tool(kind=ActionKind.CLICK, description="Click")(click)
