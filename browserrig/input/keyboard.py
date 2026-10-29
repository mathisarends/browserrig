from dataclasses import dataclass
from typing import TypedDict

from browserrig.browser.errors import BrowserError

_TYPING_INTERVAL_SECONDS = 0.05

_MODIFIERS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}
_SPECIAL_KEYS = {
    "Enter": (13, "Enter"),
    "Tab": (9, "Tab"),
    "Escape": (27, "Escape"),
    "Backspace": (8, "Backspace"),
    "Delete": (46, "Delete"),
    "ArrowLeft": (37, "ArrowLeft"),
    "ArrowUp": (38, "ArrowUp"),
    "ArrowRight": (39, "ArrowRight"),
    "ArrowDown": (40, "ArrowDown"),
    "Home": (36, "Home"),
    "End": (35, "End"),
    "PageUp": (33, "PageUp"),
    "PageDown": (34, "PageDown"),
    "Alt": (18, "AltLeft"),
    "Control": (17, "ControlLeft"),
    "Meta": (91, "MetaLeft"),
    "Shift": (16, "ShiftLeft"),
    **{f"F{number}": (111 + number, f"F{number}") for number in range(1, 13)},
}
_PUNCTUATION = {
    " ": (32, "Space"),
    "-": (189, "Minus"),
    "=": (187, "Equal"),
    "[": (219, "BracketLeft"),
    "]": (221, "BracketRight"),
    "\\": (220, "Backslash"),
    ";": (186, "Semicolon"),
    "'": (222, "Quote"),
    ",": (188, "Comma"),
    ".": (190, "Period"),
    "/": (191, "Slash"),
    "`": (192, "Backquote"),
}
_SHIFTED = dict(zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;',./`", strict=True))
_SHIFTED_BY_BASE = {base: shifted for shifted, base in _SHIFTED.items()}


class _KeyArguments(TypedDict):
    key: str
    code: str
    windows_virtual_key_code: int


@dataclass(frozen=True, slots=True)
class _Stroke:
    key: str
    modifiers: tuple[str, ...] = ()

    @property
    def flags(self) -> int:
        return sum(_MODIFIERS[name] for name in self.modifiers)

    def arguments(self) -> _KeyArguments:
        base = _SHIFTED.get(self.key, self.key)
        virtual, code = _SPECIAL_KEYS.get(self.key, _PUNCTUATION.get(base, (0, "")))
        if len(base) == 1 and base.isascii() and base.isalnum():
            virtual = ord(base.upper())
            code = f"Key{base.upper()}" if base.isalpha() else f"Digit{base}"
        return {"key": self.key, "code": code, "windows_virtual_key_code": virtual}


def _key_stroke(value: str, modifiers: tuple[str, ...]) -> _Stroke:
    if len(value) != 1 and value not in _SPECIAL_KEYS:
        raise BrowserError("Provide one character or a named key such as Escape, Enter or Tab")
    stroke = _character(value) if len(value) == 1 else _Stroke(value)
    modifiers = tuple(dict.fromkeys((*modifiers, *stroke.modifiers)))
    key = stroke.key
    if "Shift" in modifiers and len(key) == 1:
        shifted = _SHIFTED_BY_BASE.get(key, key.upper())
        if len(shifted) == 1:
            key = shifted
    return _Stroke(key, modifiers)


def _character(value: str) -> _Stroke:
    if value in {"\n", "\r"}:
        return _Stroke("Enter")
    shifted = value in _SHIFTED or value.isascii() and value.isupper()
    return _Stroke(value, ("Shift",) if shifted else ())
