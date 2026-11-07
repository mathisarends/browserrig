from cdpify.domains.page import Viewport

from browserrig.core import Geometry, traced

from .tab import Tab


@traced
async def screenshot(
    tab: Tab, geometry: Geometry | None = None, *, overlays: bool = False
) -> str:
    """Capture page pixels; application overlays are excluded unless requested."""
    if not overlays:
        async with tab.overlays.hidden():
            return await screenshot(tab, geometry, overlays=True)
    clip = (
        None
        if geometry is None
        else Viewport(
            x=geometry.x,
            y=geometry.y,
            width=geometry.width,
            height=geometry.height,
            scale=geometry.scale,
        )
    )
    result = await tab.cdp.page.capture_screenshot(
        format="png", clip=clip, capture_beyond_viewport=False
    )
    return result.data
