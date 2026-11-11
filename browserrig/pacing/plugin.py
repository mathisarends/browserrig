from harnessed import Plugin
from harnessed.kernel import PluginScope, needs

from browserrig.input import HumanMotor, Input, Motor


class InputPacing(Plugin, slot="browserrig.pacing"):
    """Operate the browser's mouse and keyboard through a `Motor`.

    The default motor types and moves the pointer at a person's pace. Pass another
    motor to change how input is performed; without this plugin it runs at full speed.
    """

    _input = needs(Input)

    def __init__(self, motor: Motor | None = None) -> None:
        super().__init__()
        self._motor = motor if motor is not None else HumanMotor()

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._input.pace(self._motor))
