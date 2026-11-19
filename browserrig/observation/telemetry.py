from harnessed.tracing import span

from .models import CapturedImage, Snapshot


def trace_capture(snapshot: Snapshot, browser_id: str, outcome: str) -> None:
    if snapshot.image is not None:
        trace_image(CapturedImage.from_snapshot(snapshot, browser_id), outcome)
        return
    with span(
        "browserrig.observation",
        **{
            "browserrig.observation.id": snapshot.id,
            "browserrig.observation.outcome": outcome,
            "browserrig.tab_id": snapshot.tab_id,
            "browserrig.document_id": snapshot.document_id,
            "browserrig.url": snapshot.url,
        },
    ):
        pass


def trace_image(
    image: CapturedImage, outcome: str, *, reused_id: str = "", request_id: str = ""
) -> None:
    geometry = image.geometry
    scale = geometry.scale if geometry is not None else 1.0
    width, height = (
        (geometry.width, geometry.height)
        if geometry is not None
        else (image.width, image.height)
    )
    with span(
        "browserrig.observation",
        **{
            "browserrig.observation.id": image.id,
            "browserrig.observation.outcome": outcome,
            "browserrig.tab_id": image.tab_id,
            "browserrig.document_id": image.document_id,
            "browserrig.url": image.url,
            "browserrig.screenshot.id": image.id,
            "browserrig.screenshot.asset_id": image.asset_id,
            "browserrig.screenshot.width": round(width * scale),
            "browserrig.screenshot.height": round(height * scale),
            "browserrig.screenshot.scale": scale,
            "browserrig.screenshot.device_scale": image.device_scale,
            "browserrig.screenshot.reused_id": reused_id or None,
            "browserrig.request.id": request_id or None,
        },
    ):
        pass
