from browserrig.browser import Tab
from browserrig.core import Generation, StaleElement

from .models import CapturedImage, Snapshot


def check_observation(
    tab: Tab, current: Generation, snapshot: Snapshot | None, *, reason: str
) -> None:
    if (
        snapshot is None
        or snapshot.tab_id != tab.id
        or snapshot.generation.state != current.state
    ):
        raise StaleElement(reason)


def check_coordinates(
    tab: Tab,
    current: Generation,
    snapshot: Snapshot | None,
    source: Snapshot | CapturedImage | None,
    *,
    dom_only: bool = False,
) -> None:
    if snapshot is None or source is None:
        raise StaleElement("Observe before using coordinates")
    if tab.id != snapshot.tab_id or tab.document_id != snapshot.document_id:
        raise StaleElement("The observed tab or document changed; observe again")
    if tab.viewport_revision != snapshot.viewport_revision:
        raise StaleElement(
            "The browser window was resized after the last observation; "
            "coordinates are outdated, observe again"
        )
    if isinstance(source, CapturedImage):
        _check_image(snapshot, source)
    layout = source.generation.layout
    if dom_only and isinstance(layout, tuple):
        layout = layout[0]
    if layout != current.layout:
        if isinstance(source, CapturedImage):
            raise StaleElement(
                "Content moved since the last shown image; screenshot again"
            )
        raise StaleElement(
            "Page layout changed; observe again before using coordinates"
        )


def _check_image(snapshot: Snapshot, image: CapturedImage) -> None:
    if (image.width, image.height) != (snapshot.width, snapshot.height):
        raise StaleElement(
            "The viewport changed size since the last shown image; screenshot again"
        )
    if image.viewport_revision != snapshot.viewport_revision:
        raise StaleElement(
            "The browser window was resized since the last shown image; screenshot again"
        )
    if (image.tab_id, image.document_id) != (snapshot.tab_id, snapshot.document_id):
        raise StaleElement(
            "The last shown image belongs to another document; screenshot again"
        )
    if image.generation.state != snapshot.generation.state:
        raise StaleElement(
            "Page state changed since the last shown image; screenshot again"
        )
