from harnessed import Inject

from browserrig.observation import Observe

from .forms import FormTools
from .keyboard import DomKeyboardTools
from .mouse import DomPointerTools


class DomTools(DomPointerTools, DomKeyboardTools, FormTools):
    """Ref-based clicks, drags, typing and native form controls."""

    async def setup(self, observe: Inject[Observe]) -> None:
        if not observe.capture_strategy.provides_dom_refs:
            raise ValueError(
                "DomTools requires a capture strategy providing DOM references"
            )
