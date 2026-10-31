from urllib.parse import urlsplit, urlunsplit

from browserrig.observation.models import Snapshot


def page_url(url: str) -> str:
    """Keep routing context without persisting credentials, OAuth queries or fragments."""
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")
    )


def page_changes(before: Snapshot | None, after: Snapshot | None) -> tuple[str, ...]:
    if after is None:
        return (
            "The page could not be captured after human control; inspect it again.",
        )
    if before is None:
        return (
            f"No baseline was available. Current page: {page_url(after.url)} "
            f"({after.title[:200]!r})",
        )
    changes = []
    if before.tab_id != after.tab_id:
        changes.append(f"Active tab: {before.tab_id} -> {after.tab_id}")
    if before.url != after.url:
        changes.append(f"URL: {page_url(before.url)} -> {page_url(after.url)}")
    if before.document_id != after.document_id:
        changes.append("The active document changed; use fresh element references.")
    if before.title != after.title:
        changes.append(f"Title: {before.title[:200]!r} -> {after.title[:200]!r}")
    old_tabs, new_tabs = {tab.id for tab in before.tabs}, {tab.id for tab in after.tabs}
    if opened := new_tabs - old_tabs:
        changes.append(f"Tabs now open that were absent before: {len(opened)}")
    if closed := old_tabs - new_tabs:
        changes.append(f"Previously open tabs now closed: {len(closed)}")
    if before.fingerprint != after.fingerprint:
        changes.append("The observed page content changed.")
    password_visible = any(
        element.input_type == "password" and element.in_viewport and not element.covered
        for element in after.elements
    )
    if password_visible:
        changes.append(
            "A password field is still visible; login success is unverified."
        )
    return tuple(changes) or ("No observable page change was detected.",)
