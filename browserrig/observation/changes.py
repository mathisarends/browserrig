from .models import Element, Offscreen, Snapshot


def decision_change(before: Snapshot, after: Snapshot) -> str:
    """Detect a new browser decision, ignoring entered values and cosmetic text changes."""
    if (before.tab_id, before.document_id, before.url) != (
        after.tab_id,
        after.document_id,
        after.url,
    ):
        return "The tab or page navigated."
    if {tab.id for tab in before.tabs} != {tab.id for tab in after.tabs}:
        return "The set of open tabs changed."
    if before.modal != after.modal or set(after.alerts) - set(before.alerts):
        return "A modal or alert appeared or changed."
    # Backend identities survive observation refreshes. Controls outside the viewport count as
    # known, so scrolling a field into view does not itself interrupt form filling.
    known: dict[tuple[str, int], Element | None] = {
        _identity(control): None for control in before.offscreen
    }
    known.update(
        (_identity(el), el) for el in before.elements if not el.covered and not el.disabled
    )
    for element in after.elements:
        if not element.in_viewport or element.covered or element.disabled:
            continue
        identity = _identity(element)
        if identity not in known:
            return "New interactive elements became available."
        previous = known[identity]
        if element.expanded is True and previous is not None and previous.expanded is not True:
            return "A control expanded."
    return ""


def _identity(control: Element | Offscreen) -> tuple[str, int]:
    return control.frame_id, control.backend_id
