"""Build DOM observations in tests without running a page model."""

from browserrig.dom import DomContent
from browserrig.observation import Snapshot

_DOM_FIELDS = frozenset(DomContent.model_fields)
_DEFAULTS = {
    "id": "observation",
    "tab_id": "tab",
    "document_id": "document",
    "url": "https://example.org",
    "title": "Page",
    "readiness": "ready",
    "width": 1280,
    "height": 800,
    "scroll_y": 0,
    "fingerprint": "test",
}


def dom_snapshot(*elements, **fields) -> Snapshot:
    """A snapshot whose targets are `elements`; DOM fields such as headings form its part."""
    dom = {key: fields.pop(key) for key in tuple(fields) if key in _DOM_FIELDS}
    return Snapshot(
        **{**_DEFAULTS, **fields}, targets=elements, parts=(DomContent(**dom),)
    )


def with_dom(snapshot: Snapshot, *, elements=None, **updates) -> Snapshot:
    """Copy `snapshot`, replacing its elements, DOM fields or snapshot fields."""
    dom = {key: updates.pop(key) for key in tuple(updates) if key in _DOM_FIELDS}
    part = snapshot.part(DomContent) or DomContent()
    parts = tuple(
        item for item in snapshot.parts if not isinstance(item, DomContent)
    ) + (part.model_copy(update=dom),)
    if elements is not None:
        updates["targets"] = tuple(elements)
    return snapshot.model_copy(update={**updates, "parts": parts})
