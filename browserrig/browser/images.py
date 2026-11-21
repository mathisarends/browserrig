from cdpify.domains.page import Viewport
from harnessed.tracing import traced

from browserrig.core import Geometry

from .errors import translate_cdp_errors
from .tab import Tab


@traced
@translate_cdp_errors("Cannot capture a page screenshot")
async def screenshot(
    tab: Tab, geometry: Geometry | None = None, *, overlays: bool = False
) -> str:
    """Capture page pixels; application overlays are excluded unless requested."""
    if not overlays:
        async with tab.overlays.hidden():
            return await screenshot(tab, geometry, overlays=True)
    clip = None
    if geometry is not None:
        # Browserrig regions are viewport-relative. CDP clips the document.
        layout = (await tab.cdp.page.get_layout_metrics()).css_layout_viewport
        clip = Viewport(
            x=layout.page_x + geometry.x,
            y=layout.page_y + geometry.y,
            width=geometry.width,
            height=geometry.height,
            scale=geometry.scale,
        )
    result = await tab.cdp.page.capture_screenshot(
        format="png", clip=clip, capture_beyond_viewport=False
    )
    return result.data
