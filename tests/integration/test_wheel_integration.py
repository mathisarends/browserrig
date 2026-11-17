import asyncio

import pytest

from browserrig import ChromeBrowser, Input, Point, wait_for_page
from browserrig.browser import Launch

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("delta_y", [600, -600])
async def test_native_wheel_scroll_has_visible_intermediate_positions(site, delta_y):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await _evaluate(
            tab,
            """scrollTo(0, 800);
            window.wheelSamples = [];
            window.wheelInputs = [];
            addEventListener('scroll', () => wheelSamples.push(scrollY));
            addEventListener('wheel', e => wheelInputs.push({
                trusted: e.isTrusted, delta: e.deltaY
            }));""",
        )
        await asyncio.sleep(0.1)
        await _evaluate(tab, "wheelSamples.length = 0")
        devices = Input(browser.input_targets.focused)
        await devices.mouse.scroll(delta_y=delta_y, point=Point(x=500, y=400))
        # Chrome may finish compositing the last native wheel event after its reply.
        await asyncio.sleep(0.2)
        state = await _evaluate(
            tab, "({y: scrollY, samples: wheelSamples, inputs: wheelInputs})"
        )
        assert state["y"] == pytest.approx(800 + delta_y, abs=2)
        intermediate = [y for y in state["samples"] if 5 < abs(y - 800) < 595]
        assert len(intermediate) >= 5
        assert all(e["trusted"] for e in state["inputs"])
        assert sum(e["delta"] for e in state["inputs"]) == pytest.approx(delta_y)
        assert max(abs(e["delta"]) for e in state["inputs"]) < 35


async def _evaluate(tab, expression):
    result = await tab.cdp.runtime.evaluate(expression=expression, return_by_value=True)
    assert result.exception_details is None
    return result.result.value
