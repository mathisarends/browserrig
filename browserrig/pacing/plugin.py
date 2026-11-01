from harnessed import Context, Inject, Plugin

from browserrig.browser import Browser
from browserrig.input import HumanMotor, Motor


class Pacing(Plugin, slot="browserrig.pacing", needs=(Browser,)):
    """Operate the browser's mouse and keyboard through a `Motor`.

    The default motor types and moves the pointer at a person's pace. Pass another
    motor to change how input is performed; without this plugin it runs at full speed.
    """

    _browser: Inject[Browser]

    def __init__(self, motor: Motor | None = None) -> None:
        super().__init__()
        self._motor = motor or HumanMotor()

    async def setup(self, ctx: Context) -> None:
        ctx.effect(self._browser.input.pace(self._motor))
