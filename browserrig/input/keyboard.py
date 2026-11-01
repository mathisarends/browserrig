from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TypedDict

from browserrig.core import BrowserError
from browserrig.events import InputEvent, KeyboardVisibilityEvent, KeyPressedEvent

from .motor import KeyStroke, Motor
from .target import Focus, InputTarget, focused

# Key events of sensitive text show this instead of the character and its modifiers.
_HIDDEN_KEY = "•"

# The one named key a keystroke plan may use, to correct a slip.
_ERASE = "Backspace"

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


@dataclass(frozen=True, slots=True)
class TypedText:
    """Text asked for and what the keys entered, which differs if a slip stayed."""

    intended: str
    entered: str

    @property
    def exact(self) -> bool:
        return self.entered == self.intended


class Keyboard:
    """The browser's one keyboard; each key or text goes to the tab focused when it starts."""

    def __init__(
        self,
        focus: Focus,
        *,
        emit: Callable[[InputTarget, InputEvent], Awaitable[None]],
        motor: Callable[[], Motor],
    ) -> None:
        self._focus = focus
        self._emit = emit
        self._motor = motor

    async def press_key(
        self,
        key: str,
        *,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> None:
        modifiers = _held(
            control=hold_control, shift=hold_shift, alt=hold_alt, meta=hold_meta
        )
        stroke = _key_stroke(key, modifiers)
        target = focused(self._focus)
        try:
            await self._emit(target, KeyboardVisibilityEvent(visible=True))
            await self._stroke(target, stroke)
        finally:
            await self._emit(target, KeyboardVisibilityEvent(visible=False))

    async def type_text(
        self,
        text: str,
        *,
        sensitive: bool = False,
        guard: Callable[[], Awaitable[None]] | None = None,
    ) -> TypedText:
        """Type `text` key by key, as the motor plans the keys.

        `sensitive` keeps the characters out of key events and requires a plan that
        types exactly `text`. `guard` runs before each key and aborts typing by raising,
        e.g. when focus left the intended field.
        """
        # CRLF is one line break. Other Unicode characters are inserted unchanged.
        text = text.replace("\r\n", "\n")
        plan = tuple(self._motor().keystrokes(text, sensitive=sensitive))
        typed = TypedText(intended=text, entered=_replay(plan))
        if sensitive and (typed.entered != text or len(plan) != len(text)):
            raise BrowserError("Sensitive text must be typed exactly, without slips")
        target = focused(self._focus)
        try:
            await self._emit(target, KeyboardVisibilityEvent(visible=True))
            for key in plan:
                if guard is not None:
                    await guard()
                await self._stroke(
                    target,
                    _Stroke("Backspace") if key.key == _ERASE else _character(key.key),
                    duration=key.delay_after,
                    sensitive=sensitive,
                )
                if key.delay_after:
                    await asyncio.sleep(key.delay_after)
        finally:
            await self._emit(target, KeyboardVisibilityEvent(visible=False))
        return typed

    async def _stroke(
        self,
        target: InputTarget,
        stroke: _Stroke,
        *,
        duration: float = 0,
        sensitive: bool = False,
    ) -> None:
        async with AsyncExitStack() as held:
            flags = 0
            for modifier in stroke.modifiers:
                arguments = _Stroke(modifier).arguments()
                held.push_async_callback(
                    target.dispatch_key,
                    "keyUp",
                    modifiers=flags,
                    **arguments,
                )
                flags |= _MODIFIERS[modifier]
                await target.dispatch_key("rawKeyDown", modifiers=flags, **arguments)
            arguments = stroke.arguments()
            held.push_async_callback(
                target.dispatch_key,
                "keyUp",
                modifiers=flags,
                **arguments,
            )
            shortcut = any(modifier != "Shift" for modifier in stroke.modifiers)
            text = ""
            if not shortcut:
                text = {"Enter": "\r", "Tab": ""}.get(
                    stroke.key, stroke.key if len(stroke.key) == 1 else ""
                )
            # Separate rawKeyDown and char so text is inserted once, including
            # Unicode without a physical mapping. Enter keeps native semantics.
            await target.dispatch_key(
                "keyDown" if stroke.key == "Enter" and not shortcut else "rawKeyDown",
                modifiers=flags,
                text="\r" if stroke.key == "Enter" and not shortcut else "",
                **arguments,
            )
            if text and stroke.key != "Enter":
                await target.dispatch_key(
                    "char", modifiers=flags, text=text, **arguments
                )
        await self._emit(
            target,
            KeyPressedEvent(
                key=_HIDDEN_KEY if sensitive else stroke.key,
                modifiers=() if sensitive else stroke.modifiers,
                duration=duration,
            ),
        )


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


def _replay(plan: Sequence[KeyStroke]) -> str:
    """The text a keystroke plan enters; rejects plans the keyboard cannot follow."""
    entered: list[str] = []
    for key in plan:
        if key.delay_after < 0:
            raise BrowserError("Keystroke delays must not be negative")
        if key.key == _ERASE:
            if not entered:
                raise BrowserError("A keystroke plan may only erase what it typed")
            entered.pop()
        elif len(key.key) == 1:
            entered.append(key.key)
        else:
            raise BrowserError(
                f"A keystroke plan types characters or Backspace, not {key.key!r}"
            )
    return "".join(entered)


def _held(*, control: bool, shift: bool, alt: bool, meta: bool) -> tuple[str, ...]:
    """The modifier names held for a key, in the order they are pressed."""
    pressed = (("Control", control), ("Shift", shift), ("Alt", alt), ("Meta", meta))
    return tuple(name for name, held in pressed if held)


def _key_stroke(value: str, modifiers: tuple[str, ...]) -> _Stroke:
    if len(value) != 1 and value not in _SPECIAL_KEYS:
        raise BrowserError(
            "Provide one character or a named key such as Escape, Enter or Tab"
        )
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
