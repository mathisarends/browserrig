from browserrig import Choreography
from browserrig.browser import TabChanged
from browserrig.events import CursorStateEvent
from tests.fakes import mounted


async def test_settled_tab_change_republishes_the_resting_cursor_for_viewers():
    async with mounted(Choreography()) as (services, ctx):
        tab = services.browser.active_tab
        published = []

        async def emit(event):
            published.append(event)

        tab.emit = emit
        # Before the pointer has rested in the tab there is nothing to republish.
        await ctx.dispatch(TabChanged(tab, settled=True))
        assert not published
        await services.input.mouse.resume()
        rest = services.input.mouse.position_in(tab.id)
        published.clear()
        await ctx.dispatch(TabChanged(tab, settled=False))
        await ctx.dispatch(TabChanged(tab, settled=True))
    assert [
        (event.x, event.y) for event in published if isinstance(event, CursorStateEvent)
    ] == [(rest.x, rest.y)]
