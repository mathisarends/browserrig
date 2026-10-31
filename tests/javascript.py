from typing import Any

from browserrig.browser.tab import Frame, Tab
from browserrig.scripts import Script
from browserrig.scripts.models import ScriptArgs


class _EvalArgs(ScriptArgs):
    expression: str


_EVALUATE: Script[_EvalArgs, Any] = Script(
    "test",
    "function browserrigTest({expression}) { return (0, eval)(expression); }",
    _EvalArgs,
    lambda value: value,
)


async def evaluate(target: Tab | Frame, expression: str) -> Any:
    frame = target if isinstance(target, Frame) else await target.main_frame()
    return await frame.run(
        _EVALUATE, _EvalArgs(expression=expression), user_gesture=True
    )
