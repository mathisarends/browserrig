from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from harnessed.tracing import traced

from browserrig.core import BrowserError
from browserrig.events import InputEvent, KeyboardVisibilityEvent, KeyPressedEvent

from .keys import Modifier, Stroke, character, held_modifiers, key_stroke
from .motor import KeyStroke, Motor
from .target import Focus, InputTarget, focused

# Key events of sensitive text show this instead of the character and its modifiers.
_HIDDEN_KEY = "•"

# The one named key a keystroke plan may use, to correct a slip.
_ERASE = "Backspace"

# How long viewers see a held modifier lit; held input is usually over sooner.
_HELD_SHOWN_SECONDS = 0.6


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

    @traced
    async def press_key(
        self,
        key: str,
        *,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> None:
        modifiers = held_modifiers(
            control=hold_control, shift=hold_shift, alt=hold_alt, meta=hold_meta
        )
        stroke = key_stroke(key, modifiers)
        target = focused(self._focus)
        try:
            await self._emit(target, KeyboardVisibilityEvent(visible=True))
            await self._stroke(target, stroke)
        finally:
            await self._emit(target, KeyboardVisibilityEvent(visible=False))

    @asynccontextmanager
    async def hold(self, *modifiers: str) -> AsyncGenerator[int]:
        """Hold `modifiers` down, such as Control for a click into a new tab.

        Yields the modifier flags that input sent meanwhile must carry.
        """
        if not modifiers:
            raise BrowserError("Hold one or more of Alt, Control, Meta or Shift")
        try:
            parsed_modifiers = tuple(Modifier(name) for name in modifiers)
        except ValueError as error:
            raise BrowserError(
                "Hold one or more of Alt, Control, Meta or Shift"
            ) from error
        target = focused(self._focus)
        async with AsyncExitStack() as held:
            await self._emit(target, KeyboardVisibilityEvent(visible=True))
            held.push_async_callback(
                self._emit, target, KeyboardVisibilityEvent(visible=False)
            )
            flags = 0
            for modifier in parsed_modifiers:
                arguments = Stroke(modifier).arguments()
                held.push_async_callback(
                    target.dispatch_key, "keyUp", modifiers=flags, **arguments
                )
                flags |= modifier.flag
                await target.dispatch_key("rawKeyDown", modifiers=flags, **arguments)
            await self._emit(
                target,
                KeyPressedEvent(
                    key=modifiers[-1],
                    modifiers=modifiers[:-1],
                    duration=_HELD_SHOWN_SECONDS,
                ),
            )
            yield flags

    @traced
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
        motor = self._motor()
        plan = tuple(motor.keystrokes(text, sensitive=sensitive))
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
                    Stroke("Backspace") if key.key == _ERASE else character(key.key),
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
        stroke: Stroke,
        *,
        duration: float = 0,
        sensitive: bool = False,
    ) -> None:
        async with AsyncExitStack() as held:
            flags = 0
            for modifier in stroke.modifiers:
                arguments = Stroke(modifier).arguments()
                held.push_async_callback(
                    target.dispatch_key,
                    "keyUp",
                    modifiers=flags,
                    **arguments,
                )
                flags |= modifier.flag
                await target.dispatch_key("rawKeyDown", modifiers=flags, **arguments)
            arguments = stroke.arguments()
            held.push_async_callback(
                target.dispatch_key,
                "keyUp",
                modifiers=flags,
                **arguments,
            )
            shortcut = any(modifier != Modifier.SHIFT for modifier in stroke.modifiers)
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
