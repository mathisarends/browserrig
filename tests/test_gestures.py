import asyncio
from types import SimpleNamespace

import pytest

from browserrig.browser.models import Point
from browserrig.tools.gestures import drag


async def test_cancelled_drag_releases_mouse_button():
    entered = asyncio.Event()
    commands = []

    async def dispatch(**arguments):
        commands.append(arguments)
        if arguments["type"] == "mouseMoved" and arguments.get("buttons") == 1:
            entered.set()
            await asyncio.Event().wait()

    tab = SimpleNamespace(cdp=SimpleNamespace(input=SimpleNamespace(dispatch_mouse_event=dispatch)))
    task = asyncio.create_task(
        drag(tab, start=Point(x=10, y=10), end=Point(x=200, y=200), duration=1)
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["buttons"] == 0
