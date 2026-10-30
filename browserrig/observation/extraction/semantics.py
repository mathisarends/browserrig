"""ARIA roles, accessible names, values and states derived from the DOM snapshot.

This follows the parts of HTML-AAM and accname that matter for acting on a page,
without the cost of fetching Chrome's full accessibility tree.
"""

from ..models import Option, Tristate
from .document import Document, clean

INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "checkbox",
        "combobox",
        "link",
        "listbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "textbox",
        "treeitem",
    }
)
CHECKABLE_ROLES = frozenset({"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"})

_INPUT_ROLES = {
    "button": "button",
    "submit": "button",
    "reset": "button",
    "image": "button",
    "file": "button",
    "checkbox": "checkbox",
    "radio": "radio",
    "range": "slider",
    "number": "spinbutton",
    "search": "searchbox",
}
_TAG_ROLES = {
    "button": "button",
    "summary": "button",
    "textarea": "textbox",
    "option": "option",
    "nav": "navigation",
    "main": "main",
    "aside": "complementary",
    "dialog": "dialog",
    "form": "form",
    "fieldset": "group",
    "details": "group",
    "ul": "list",
    "ol": "list",
    "menu": "list",
    "li": "listitem",
    "table": "table",
    "progress": "progressbar",
    "meter": "meter",
    "output": "status",
    "search": "search",
    **{f"h{level}": "heading" for level in range(1, 7)},
}
_SCOPING = frozenset({"article", "aside", "main", "nav", "section"})
_NAME_FROM_CONTENT_EXCLUDED = frozenset(
    {"textbox", "searchbox", "combobox", "listbox", "slider", "spinbutton", "progressbar", "meter"}
)
_RANGE_ROLES = frozenset({"slider", "spinbutton", "progressbar", "meter", "scrollbar"})
_NO_VALUE_TYPES = frozenset(
    {"checkbox", "radio", "button", "submit", "reset", "image", "hidden", "password"}
)
_BUTTON_DEFAULTS = {"submit": "Submit", "reset": "Reset", "file": "Choose file"}
_EDITABLE = frozenset({"", "true", "plaintext-only"})
_DISABLEABLE = frozenset(
    {"button", "input", "select", "textarea", "option", "optgroup", "fieldset"}
)


def input_type(document: Document, index: int) -> str:
    if document.tag(index) != "input":
        return ""
    return document.attributes(index).get("type", "text").strip().lower() or "text"


def editable(document: Document, index: int) -> bool:
    state = document.attributes(index).get("contenteditable")
    return state is not None and state.strip().lower() in _EDITABLE


def role(document: Document, index: int) -> str:
    """The explicit role when present, otherwise the element's implicit role."""
    explicit = document.attributes(index).get("role", "").strip().lower().split()
    if explicit and explicit[0] not in ("none", "presentation", "generic"):
        return explicit[0]
    return _implicit_role(document, index)


def name(document: Document, index: int, element_role: str) -> str:
    """Accessible name: aria-labelledby, aria-label, native labels, content, then title."""
    attributes = document.attributes(index)
    return (
        labelled_by(document, index)
        or clean(attributes.get("aria-label", ""))
        or _own_name(document, index, element_role, attributes)
        or clean(attributes.get("title", ""))
    )


def labelled_by(document: Document, index: int) -> str:
    references = document.attributes(index).get("aria-labelledby", "").split()
    parts = []
    for reference in references:
        target = document.element_by_id(reference)
        if target is not None:
            attributes = document.attributes(target)
            parts.append(
                clean(attributes.get("aria-label", ""))
                or document.text(target)
                or clean(attributes.get("title", ""))
            )
    return clean(" ".join(part for part in parts if part))


def value(document: Document, index: int, element_role: str, kind: str) -> str | None:
    attributes = document.attributes(index)
    if element_role in _RANGE_ROLES:
        text = attributes.get("aria-valuetext") or attributes.get("aria-valuenow")
        if text:
            return clean(text)
    tag = document.tag(index)
    if tag == "select":
        chosen = [option.label for option in options(document, index) if option.selected]
        return ", ".join(chosen) or None
    if tag in ("input", "textarea"):
        if kind in _NO_VALUE_TYPES:
            return None
        return clean(document.input_value(index) or "", 200) or None
    if editable(document, index) or element_role in ("textbox", "searchbox", "combobox"):
        return document.text(index, 200) or None
    return None


def options(document: Document, index: int) -> tuple[Option, ...]:
    result = []
    for node in document.descendants(index, frozenset({"option"})):
        attributes = document.attributes(node)
        parent = document.parent(node)
        group_disabled = document.tag(parent) == "optgroup" and "disabled" in document.attributes(
            parent
        )
        result.append(
            Option(
                label=clean(attributes.get("label", "")) or document.own_text(node, 80),
                selected=node in document.selected,
                disabled="disabled" in attributes or group_disabled,
            )
        )
    return tuple(result)


def checked(document: Document, index: int, element_role: str) -> Tristate:
    if document.tag(index) == "input" and input_type(document, index) in ("checkbox", "radio"):
        return index in document.checked
    state = _tristate(document.attributes(index).get("aria-checked"))
    if state is None and element_role in CHECKABLE_ROLES:
        return False
    return state


def pressed(document: Document, index: int) -> Tristate:
    return _tristate(document.attributes(index).get("aria-pressed"))


def expanded(document: Document, index: int) -> bool | None:
    if document.tag(index) == "summary":
        parent = document.parent(index)
        if parent >= 0 and document.tag(parent) == "details":
            return "open" in document.attributes(parent)
    state = _tristate(document.attributes(index).get("aria-expanded"))
    return state if isinstance(state, bool) else None


def selected(document: Document, index: int) -> bool:
    if document.tag(index) == "option":
        return index in document.selected
    return document.attributes(index).get("aria-selected", "").lower() == "true"


def disabling_ancestors(document: Document) -> list[int]:
    """Nodes whose subtree is disabled: aria-disabled="true" or a disabled <fieldset>."""
    roots = []
    for index in document.with_any_attribute(("aria-disabled", "disabled")):
        attributes = document.attributes(index)
        if attributes.get("aria-disabled", "").lower() == "true" or (
            document.tag(index) == "fieldset" and "disabled" in attributes
        ):
            roots.append(index)
    return sorted(roots)


def disabled(document: Document, index: int, roots: list[int]) -> bool:
    """`roots` comes from `disabling_ancestors`; fieldsets only disable form controls."""
    attributes = document.attributes(index)
    if attributes.get("aria-disabled", "").lower() == "true":
        return True
    tag = document.tag(index)
    if tag in _DISABLEABLE and "disabled" in attributes:
        return True
    for root in roots:
        if root >= index:
            break
        if document.contains(root, index) and (
            tag in _DISABLEABLE or document.tag(root) != "fieldset"
        ):
            return True
    return False


def flag(document: Document, index: int, native: str, aria: str) -> bool:
    attributes = document.attributes(index)
    return native in attributes or attributes.get(aria, "").lower() == "true"


def invalid(document: Document, index: int) -> bool:
    return document.attributes(index).get("aria-invalid", "false").lower() not in ("false", "")


def has_popup(document: Document, index: int) -> str:
    popup = document.attributes(index).get("aria-haspopup", "").lower()
    if popup in ("", "false"):
        return ""
    return "menu" if popup == "true" else popup


def current(document: Document, index: int) -> str:
    state = document.attributes(index).get("aria-current", "").lower()
    if state in ("", "false"):
        return ""
    return "true" if state == "true" else state


def heading_level(document: Document, index: int) -> int:
    level = _number(document.attributes(index).get("aria-level"))
    if level:
        return level
    tag = document.tag(index)
    return int(tag[1]) if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit() else 2


def _implicit_role(document: Document, index: int) -> str:
    tag = document.tag(index)
    attributes = document.attributes(index)
    if tag in ("a", "area"):
        return "link" if "href" in attributes else ""
    if tag == "input":
        default = "combobox" if "list" in attributes else "textbox"
        return _INPUT_ROLES.get(input_type(document, index), default)
    if tag == "select":
        multiple = "multiple" in attributes or _number(attributes.get("size")) > 1
        return "listbox" if multiple else "combobox"
    if tag in ("img", "header", "footer", "section"):
        return _conditional_role(document, index, tag, attributes)
    return "textbox" if editable(document, index) else _TAG_ROLES.get(tag, "")


def _conditional_role(document: Document, index: int, tag: str, attributes: dict[str, str]) -> str:
    """Roles that images, headers, footers and sections only get in some contexts."""
    if tag == "img":
        return "img" if attributes.get("alt") != "" else ""
    if tag == "section":
        return "region" if "aria-label" in attributes or "aria-labelledby" in attributes else ""
    if any(document.tag(parent) in _SCOPING for parent in document.ancestors(index)):
        return ""
    return "banner" if tag == "header" else "contentinfo"


def _own_name(document: Document, index: int, element_role: str, attributes: dict[str, str]) -> str:
    tag = document.tag(index)
    if tag in ("input", "select", "textarea", "meter", "progress"):
        return _control_name(document, index, attributes)
    if tag == "img":
        return clean(attributes.get("alt", ""))
    if tag == "fieldset":
        legends = document.descendants(index, frozenset({"legend"}))
        return document.text(legends[0]) if legends else ""
    return "" if element_role in _NAME_FROM_CONTENT_EXCLUDED else document.text(index)


def _control_name(document: Document, index: int, attributes: dict[str, str]) -> str:
    labels = clean(" ".join(document.text(label) for label in document.labels(index)))
    if labels:
        return labels
    kind = input_type(document, index)
    if kind in ("button", "submit", "reset"):
        return clean(attributes.get("value", _BUTTON_DEFAULTS.get(kind, "")))
    if kind == "image":
        return clean(attributes.get("alt", "") or attributes.get("value", ""))
    return _BUTTON_DEFAULTS["file"] if kind == "file" else ""


def _tristate(raw: str | None) -> Tristate:
    match (raw or "").strip().lower():
        case "true":
            return True
        case "false":
            return False
        case "mixed":
            return "mixed"
        case _:
            return None


def _number(raw: str | None) -> int:
    try:
        return int((raw or "").strip())
    except ValueError:
        return 0
