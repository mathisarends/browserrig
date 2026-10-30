from .models import Element, Snapshot


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
    # Backend identities survive observation refreshes. Include offscreen controls in the
    # baseline so scrolling a field into view does not itself interrupt form filling.
    known = {_identity(el): el for el in before.elements if not el.covered and not el.disabled}
    for element in after.elements:
        if not element.in_viewport or element.covered or element.disabled:
            continue
        previous = known.get(_identity(element))
        if previous is None:
            return "New interactive elements became available."
        if element.expanded is True and previous.expanded is not True:
            return "A control expanded."
    return ""


def _identity(element: Element) -> tuple[str, int]:
    return element.frame_id, element.backend_id
