from harnessed import Plugin
from harnessed.kernel import PluginScope, needs

from browserrig.input import HumanMotor, Input, Motor

from .planners import KeystrokePlanner, PointerRoutePlanner, compose


class InputPacing(Plugin, slot="browserrig.pacing"):
    """Operate the browser's mouse and keyboard through a `Motor`.

    The default motor types, moves the pointer and scrolls at a person's pace.
    Override individual plans with `keystrokes` and `pointer_route`.
    Pass another motor to change how input is performed; without this plugin it
    runs at full speed.
    """

    _input = needs(Input)

    def __init__(
        self,
        motor: Motor | None = None,
        *,
        keystrokes: KeystrokePlanner | None = None,
        pointer_route: PointerRoutePlanner | None = None,
    ) -> None:
        super().__init__()
        base = motor if motor is not None else HumanMotor()
        self._motor = compose(base, keystrokes, pointer_route)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._input.pace(self._motor))
