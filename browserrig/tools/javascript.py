from typing import Annotated

from harnessed import Inject, Plugin, ToolResult
from pydantic import Field

from browserrig.browser.tab import Tab
from browserrig.core.kinds import ActionKind
from browserrig.core.tools import browser_tool as tool

from .execution import Actions, Effect


class JavaScriptTools(Plugin, needs=(Actions,)):
    @tool(
        kind=ActionKind.JAVASCRIPT,
        description=(
            "Execute JavaScript in the active tab's main page context via Runtime.evaluate. "
            "Supports top-level await and retains variables until navigation. Use await for "
            "Promise results. Returns the last "
            "expression's value as JSON, or a JavaScript value such as undefined or NaN. "
            "Return serializable data when inspecting objects. Errors are reported in the tool "
            "result. timeout is in seconds."
        ),
    )
    async def execute_javascript(
        self,
        code: str,
        timeout: Annotated[float, Field(gt=0, le=30)] = 10,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def execute(tab: Tab) -> Effect:
            result = await tab.evaluate(code, timeout=timeout)
            return Effect(f"JavaScript result:\n{result}")

        return await actions.run(kind=ActionKind.JAVASCRIPT, operation=execute)
