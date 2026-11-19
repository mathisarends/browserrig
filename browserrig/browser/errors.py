from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any

from cdpify import CDPError

from browserrig.core import BrowserError


def translate_cdp_errors[**P, T](
    message: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Keep transport errors as causes and expose an operation-specific message."""

    def decorate(
        operation: Callable[P, Awaitable[T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(operation)
        async def translated(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return await operation(*args, **kwargs)
            except CDPError as error:
                raise BrowserError(message) from error

        return translated

    return decorate
