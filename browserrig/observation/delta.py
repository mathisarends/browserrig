"""Describe an observation as line changes to the last complete one of the same page.

Typing into a field or opening a menu changes a few lines of an observation; repeating
the unchanged rest costs context on every step. The header (title, URL, scroll, cursor)
is always repeated in full, and changed lines keep their section and group lines so they
read in place.
"""

import re
from difflib import SequenceMatcher

_NEW_MARK = re.compile(r"^(\s*(?:#+ )?)\*\[")
_CONTEXT = re.compile(r"^\s*(?:\[[A-Z][A-Z_ ]*(?:: .*)?\]|<.*>)$")

INTRO = (
    "changes since the last complete observation of this page "
    "(unchanged lines omitted; - removed, + added):"
)


def unmarked(text: str) -> str:
    """Drop new-element marks, which depend on the previous capture rather than the page."""
    return "\n".join(_NEW_MARK.sub(r"\1[", line) for line in text.split("\n"))


def delta(base: str, current: str) -> str:
    """``current`` as its header plus the body lines that differ from ``base``."""
    _, old = _split(base)
    header, new = _split(current)
    lines = [*header, "", INTRO]
    shown: list[str] = []
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        context = _context(new, j1) if j2 > j1 else _context(old, i1)
        lines.extend(line for line in context if line not in shown)
        shown = context
        lines.extend(_mark("-", line) for line in old[i1:i2])
        lines.extend(_mark("+", line) for line in new[j1:j2])
    if len(lines) == len(header) + 2:
        lines.append("  (no changes)")
    return "\n".join(lines)


def _split(text: str) -> tuple[list[str], list[str]]:
    lines = text.split("\n")
    end = lines.index("") if "" in lines else len(lines)
    return lines[:end], lines[end + 1 :]


def _mark(sign: str, line: str) -> str:
    # Keep indentation aligned with the context lines.
    return sign + line[1:] if line.startswith(" ") else f"{sign} {line}"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _context(lines: list[str], index: int) -> list[str]:
    """The section and group lines enclosing ``lines[index]``, outermost first."""
    found: list[str] = []
    depth = _indent(lines[index]) if index < len(lines) else 1 << 30
    for line in reversed(lines[:index]):
        if _CONTEXT.match(line) and _indent(line) < depth:
            found.insert(0, line)
            depth = _indent(line)
    return found
