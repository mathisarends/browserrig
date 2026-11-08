"""Conservative consent-UI heuristics over the existing composed DOM snapshot.

Text alone is not a banner: a candidate needs visible decision controls and either
overlay/dialog presentation or consent-specific container metadata. An unstyled
container can also qualify when it offers both acceptance and rejection. No page
input or consent policy belongs here.
"""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable

from browserrig.observation.models import CookieBanner, Element

from . import semantics
from .document import Document, Rect, clean
from .styles import Style
from .visibility import hidden, visible_area

_COOKIE = re.compile(r"\bcookies?\b", re.IGNORECASE)
_PRIVACY = re.compile(
    r"consent|einwillig|datenschutz|privacy|consentement|consentimiento", re.IGNORECASE
)
_CONTAINER = re.compile(
    r"(?:cookie|consent)[\w -]*(?:banner|notice|dialog|popup|wall|preferences|settings|manager)"
    r"|(?:banner|notice|dialog|popup)[\w -]*(?:cookie|consent)"
    r"|onetrust-(?:banner|pc)-sdk|cybotcookiebotdialog|usercentrics|didomi"
    r"|qc-cmp2|sp_message_container|truste-consent",
    re.IGNORECASE,
)
_ACCEPT = re.compile(
    r"\b(?:accept|agree|allow|akzeptier\w*|zustimm\w*|erlaub\w*|accepter|aceptar|accetta)\b",
    re.IGNORECASE,
)
_REJECT = re.compile(
    r"\b(?:reject|decline|deny|refuse|ablehn\w*|verweigern|refuser|rechazar|rifiuta)\b"
    r"|(?:only|nur)[\w ]*(?:necessary|essential|notwendig|erforderlich)"
    r"|(?:necessary|essential)[\w ]*only",
    re.IGNORECASE,
)
_SAVE = re.compile(
    r"\b(?:save|confirm|speichern|bestätigen|enregistrer|guardar)\b", re.IGNORECASE
)
_ACKNOWLEDGE = re.compile(
    r"^(?:ok(?:ay)?|got it|verstanden|alles klar)[.! ]*$", re.IGNORECASE
)
_CHOICE_ROLES = frozenset({"button", "link", "generic", ""})
_EXCLUDED = frozenset({"html", "body", "main", "article", "nav"})
_MAX_TEXT = 4000
_EXCERPT = 600


def cookie_banners(
    document: Document,
    elements: list[tuple[int, Element]],
    *,
    viewport: Rect | None,
    covered: Callable[[int, Rect], bool],
    modal: int | None,
    embedded: bool,
) -> tuple[CookieBanner, ...]:
    """Recognize visible regions; deepest matches win over duplicate outer wrappers."""
    controls = [(node, el) for node, el in elements if el.in_viewport]
    candidates: dict[int, list[Element]] = {}
    for node, element in controls:
        for ancestor in document.ancestors(node):
            if not document.is_element(ancestor):
                continue
            if document.tag(ancestor) in _EXCLUDED and not (
                embedded and document.tag(ancestor) == "body"
            ):
                continue
            candidates.setdefault(ancestor, []).append(element)
    # Most pages have no consent decisions, so avoid collecting their text at all.
    candidates = {
        node: children
        for node, children in candidates.items()
        if _decisions(children)[0]
    }
    if not candidates:
        return ()
    runs = [
        (node, text)
        for node, text, rect in document.text_runs()
        if (area := visible_area(document, document.parent(node), rect, viewport))
        is not None
        and not covered(document.parent(node), area)
    ]
    indexes = [node for node, _ in runs]
    control_nodes = [node for node, _ in controls]
    context_runs: list[tuple[int, str]] = []
    for node, value in runs:
        position = bisect_right(control_nodes, node) - 1
        if position < 0 or node >= document.end(control_nodes[position]):
            context_runs.append((node, value))
    context_indexes = [node for node, _ in context_runs]
    found: list[tuple[int, CookieBanner]] = []
    for node, children in sorted(candidates.items(), reverse=True):
        if any(document.contains(node, child) for child, _ in found):
            continue
        rect = document.rect(node)
        if rect is None or hidden(document, node, rect):
            continue
        area = visible_area(document, node, rect, viewport)
        if area is None or covered(node, area):
            continue
        name = semantics.labelled_by(document, node) or clean(
            document.attributes(node).get("aria-label", ""), 80
        )
        text = _text(runs, indexes, node, document.end(node))
        context = _text(context_runs, context_indexes, node, document.end(node))
        if not _matches(document, node, children, f"{name} {context}", text):
            continue
        found.append(
            (
                node,
                CookieBanner(
                    name=name
                    or _heading(document, node, viewport, covered)
                    or "Cookie consent",
                    text=text if len(text) <= _EXCERPT else text[: _EXCERPT - 1] + "…",
                    refs=tuple(element.ref for element in children),
                    modal=modal is not None
                    and (
                        node == modal
                        or document.contains(modal, node)
                        or document.contains(node, modal)
                    ),
                ),
            )
        )
    return tuple(banner for _, banner in sorted(found))


def _matches(
    document: Document,
    node: int,
    controls: list[Element],
    context: str,
    text: str,
) -> bool:
    attributes = document.attributes(node)
    metadata = " ".join(
        attributes.get(key, "") for key in ("id", "class", "data-testid")
    )
    identified = bool(_CONTAINER.search(metadata))
    dialog = semantics.role(document, node) in ("dialog", "alertdialog")
    positioned = document.style(node, Style.POSITION) in ("fixed", "sticky", "absolute")
    cookie = bool(_COOKIE.search(context)) or (
        identified and bool(_COOKIE.search(text))
    )
    privacy = bool(_PRIVACY.search(context))
    _, alternatives = _decisions(controls)
    # A footer launcher or a privacy-policy link alone never supplies a decision.
    # Vendor/container names only corroborate visible content and choices.
    return (cookie and (identified or dialog or positioned or alternatives)) or (
        privacy and (identified or ((dialog or positioned) and alternatives))
    )


def _decisions(elements: list[Element]) -> tuple[bool, bool]:
    labels = [el.name for el in elements if el.role in _CHOICE_ROLES]
    accepts = any(_ACCEPT.search(label) for label in labels)
    rejects = any(_REJECT.search(label) for label in labels)
    decides = (
        accepts
        or rejects
        or any(_SAVE.search(label) or _ACKNOWLEDGE.fullmatch(label) for label in labels)
    )
    return decides, accepts and rejects


def _text(
    runs: list[tuple[int, str]], indexes: list[int], start: int, stop: int
) -> str:
    parts: list[str] = []
    length = 0
    for position in range(bisect_left(indexes, start), bisect_left(indexes, stop)):
        value = runs[position][1]
        parts.append(value)
        length += len(value) + 1
        if length >= _MAX_TEXT:
            break
    return clean(" ".join(parts), _MAX_TEXT)


def _heading(
    document: Document,
    root: int,
    viewport: Rect | None,
    covered: Callable[[int, Rect], bool],
) -> str:
    for node in document.descendants(root, frozenset({"h1", "h2", "h3", "h4"})):
        rect = document.rect(node)
        if (
            rect is not None
            and not hidden(document, node, rect)
            and (area := visible_area(document, node, rect, viewport)) is not None
            and not covered(node, area)
        ):
            return document.text(node, 80)
    return ""
