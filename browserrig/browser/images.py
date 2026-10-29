from cdpify.domains.page import Viewport

from browserrig.core.geometry import Geometry

from .tab import Tab


async def screenshot(tab: Tab, geometry: Geometry | None = None) -> str:
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
