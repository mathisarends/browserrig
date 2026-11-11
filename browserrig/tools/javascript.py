from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool

from .effects import Effect
from .execution import Actions


class JavaScriptTools(Plugin):
    _actions = needs(Actions)

    @tool(
        kind=ActionKind.JAVASCRIPT,
        description=(
            "Run JavaScript in the active page; variables persist until navigation."
        ),
    )
    async def execute_javascript(
        self,
        code: Annotated[
            str,
            Field(
                description="Supports top-level await; await promises and return serializable data."
            ),
        ],
        timeout: Annotated[
            float, Field(gt=0, le=30, description="Execution timeout in seconds.")
        ] = 10,
    ) -> Effect:
        result = await self._actions.tab.evaluate(code, timeout=timeout)
        return Effect(f"JavaScript result:\n{result}")
