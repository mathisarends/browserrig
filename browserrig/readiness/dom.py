from importlib.resources import files

from browserrig.browser.config import Options
from browserrig.browser.tab import Tab

SCRIPT = files("browserrig.readiness").joinpath("scripts/dom.js").read_text(encoding="utf-8")


class DOMProbe(Options):
    loaded: bool
    body: bool
    quiet_ms: float
    width: float
    height: float


async def probe_dom(tab: Tab) -> DOMProbe:
    return DOMProbe.model_validate(await tab.evaluate(SCRIPT))
