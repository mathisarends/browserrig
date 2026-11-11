from typing import Annotated

from harnessed import Plugin, ToolError
from harnessed.kernel import needs, observes
from pydantic import Field

from browserrig.browser import Browser
from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool
from browserrig.input import TypedText
from browserrig.secrets import Secrets

from .effects import Effect
from .execution import Actions


class KeyboardTools(Plugin):
    """Native keyboard input to the current focus, without DOM field capabilities."""

    _actions = needs(Actions)
    _browser = needs(Browser)
    _secrets = observes(Secrets)

    @tool(
        kind=ActionKind.PRESS,
        chainable=True,
        description="Send text or a key to the current focus; choose exactly one.",
    )
    async def send_keys(
        self,
        *,
        text: str | None = None,
        key: Annotated[
            str | None,
            Field(
                description="Character or named key, e.g. Enter or Tab. Modifiers apply only here."
            ),
        ] = None,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> Effect:
        if (text is None) == (key is None):
            raise ToolError("Provide exactly one of text or key")
        if text is not None and any((hold_control, hold_shift, hold_alt, hold_meta)):
            raise ToolError("Modifier flags require key")

        if key is not None:
            await self._browser.input.keyboard.press_key(
                key,
                hold_control=hold_control,
                hold_shift=hold_shift,
                hold_alt=hold_alt,
                hold_meta=hold_meta,
            )
            return Effect("Key dispatched.")
        assert text is not None
        secrets = self._secrets
        if secrets is not None:
            entry = await secrets.prepare(text, browser=self._browser)
            if entry is not None:
                return _secret_entered(
                    await secrets.enter(entry, self._browser.input.keyboard)
                )
        return _entered(await self._browser.input.keyboard.type_text(text))


def _entered(typed: TypedText) -> Effect:
    if typed.exact:
        return Effect("Text entered.")
    return Effect(
        f"Text entered with a slip: typed {typed.entered!r} instead of "
        f"{typed.intended!r}. Check the field before continuing.",
        break_chain=True,
    )


def _secret_entered(exact: bool) -> Effect:
    if exact:
        return Effect("Text entered.")
    # Never echo text that surrounds a secret.
    return Effect(
        "Text entered with a slip in the text around the secret. "
        "Check the field before continuing.",
        break_chain=True,
    )
