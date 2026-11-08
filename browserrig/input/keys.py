"""Typed key descriptions and their US keyboard mappings for native input."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, TypedDict

from browserrig.core import BrowserError


class Modifier(StrEnum):
    ALT = "Alt"
    CONTROL = "Control"
    META = "Meta"
    SHIFT = "Shift"

    @property
    def flag(self) -> int:
        """The bit carried by native input while this modifier is held."""
        match self:
            case Modifier.ALT:
                return 1
            case Modifier.CONTROL:
                return 2
            case Modifier.META:
                return 4
            case Modifier.SHIFT:
                return 8


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyDefinition:
    windows_virtual_key_code: int
    code: str


class KeyArguments(TypedDict):
    key: str
    code: str
    windows_virtual_key_code: int


@dataclass(frozen=True, slots=True)
class Stroke:
    key: str
    modifiers: tuple[Modifier, ...] = ()

    def arguments(self) -> KeyArguments:
        base = _SHIFTED.get(self.key, self.key)
        definition = _SPECIAL_KEYS.get(self.key) or _PUNCTUATION.get(base)
        virtual = definition.windows_virtual_key_code if definition else 0
        code = definition.code if definition else ""
        if len(base) == 1 and base.isascii() and base.isalnum():
            virtual = ord(base.upper())
            code = f"Key{base.upper()}" if base.isalpha() else f"Digit{base}"
        return {"key": self.key, "code": code, "windows_virtual_key_code": virtual}


def held_modifiers(
    *, control: bool, shift: bool, alt: bool, meta: bool
) -> tuple[Modifier, ...]:
    """The modifiers held for a key, in the order they are pressed."""
    pressed = (
        (Modifier.CONTROL, control),
        (Modifier.SHIFT, shift),
        (Modifier.ALT, alt),
        (Modifier.META, meta),
    )
    return tuple(modifier for modifier, held in pressed if held)


def key_stroke(value: str, modifiers: tuple[Modifier, ...]) -> Stroke:
    if len(value) != 1 and value not in _SPECIAL_KEYS:
        raise BrowserError(
            "Provide one character or a named key such as Escape, Enter or Tab"
        )
    stroke = character(value) if len(value) == 1 else Stroke(value)
    modifiers = tuple(dict.fromkeys((*modifiers, *stroke.modifiers)))
    key = stroke.key
    if Modifier.SHIFT in modifiers and len(key) == 1:
        shifted = _SHIFTED_BY_BASE.get(key, key.upper())
        if len(shifted) == 1:
            key = shifted
    return Stroke(key, modifiers)


def character(value: str) -> Stroke:
    if value in {"\n", "\r"}:
        return Stroke("Enter")
    shifted = value in _SHIFTED or value.isascii() and value.isupper()
    return Stroke(value, (Modifier.SHIFT,) if shifted else ())


_SPECIAL_KEYS: Final[Mapping[str, KeyDefinition]] = {
    "Enter": KeyDefinition(windows_virtual_key_code=13, code="Enter"),
    "Tab": KeyDefinition(windows_virtual_key_code=9, code="Tab"),
    "Escape": KeyDefinition(windows_virtual_key_code=27, code="Escape"),
    "Backspace": KeyDefinition(windows_virtual_key_code=8, code="Backspace"),
    "Delete": KeyDefinition(windows_virtual_key_code=46, code="Delete"),
    "ArrowLeft": KeyDefinition(windows_virtual_key_code=37, code="ArrowLeft"),
    "ArrowUp": KeyDefinition(windows_virtual_key_code=38, code="ArrowUp"),
    "ArrowRight": KeyDefinition(windows_virtual_key_code=39, code="ArrowRight"),
    "ArrowDown": KeyDefinition(windows_virtual_key_code=40, code="ArrowDown"),
    "Home": KeyDefinition(windows_virtual_key_code=36, code="Home"),
    "End": KeyDefinition(windows_virtual_key_code=35, code="End"),
    "PageUp": KeyDefinition(windows_virtual_key_code=33, code="PageUp"),
    "PageDown": KeyDefinition(windows_virtual_key_code=34, code="PageDown"),
    Modifier.ALT: KeyDefinition(windows_virtual_key_code=18, code="AltLeft"),
    Modifier.CONTROL: KeyDefinition(windows_virtual_key_code=17, code="ControlLeft"),
    Modifier.META: KeyDefinition(windows_virtual_key_code=91, code="MetaLeft"),
    Modifier.SHIFT: KeyDefinition(windows_virtual_key_code=16, code="ShiftLeft"),
    **{
        f"F{number}": KeyDefinition(
            windows_virtual_key_code=111 + number, code=f"F{number}"
        )
        for number in range(1, 13)
    },
}
_PUNCTUATION: Final[Mapping[str, KeyDefinition]] = {
    " ": KeyDefinition(windows_virtual_key_code=32, code="Space"),
    "-": KeyDefinition(windows_virtual_key_code=189, code="Minus"),
    "=": KeyDefinition(windows_virtual_key_code=187, code="Equal"),
    "[": KeyDefinition(windows_virtual_key_code=219, code="BracketLeft"),
    "]": KeyDefinition(windows_virtual_key_code=221, code="BracketRight"),
    "\\": KeyDefinition(windows_virtual_key_code=220, code="Backslash"),
    ";": KeyDefinition(windows_virtual_key_code=186, code="Semicolon"),
    "'": KeyDefinition(windows_virtual_key_code=222, code="Quote"),
    ",": KeyDefinition(windows_virtual_key_code=188, code="Comma"),
    ".": KeyDefinition(windows_virtual_key_code=190, code="Period"),
    "/": KeyDefinition(windows_virtual_key_code=191, code="Slash"),
    "`": KeyDefinition(windows_virtual_key_code=192, code="Backquote"),
}
_SHIFTED: Final[Mapping[str, str]] = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}
_SHIFTED_BY_BASE: Final[Mapping[str, str]] = {
    base: shifted for shifted, base in _SHIFTED.items()
}
