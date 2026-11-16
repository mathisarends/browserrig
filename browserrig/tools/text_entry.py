from browserrig.input import TypedText

from .effects import Effect


def entered(typed: TypedText) -> Effect:
    if typed.exact:
        return Effect("Text entered.")
    return Effect(
        f"Text entered with a slip: typed {typed.entered!r} instead of "
        f"{typed.intended!r}. Check the field before continuing.",
        break_chain=True,
    )


def secret_entered(exact: bool) -> Effect:
    if exact:
        return Effect("Text entered.")
    # Never echo text that surrounds a secret.
    return Effect(
        "Text entered with a slip in the text around the secret. "
        "Check the field before continuing.",
        break_chain=True,
    )
