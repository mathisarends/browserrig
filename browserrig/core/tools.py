from collections.abc import Callable
from dataclasses import dataclass

from harnessed import ToolChain, tool

from .kinds import ActionKind


@dataclass(frozen=True, slots=True)
class BrowserToolMetadata:
    """Process-local browser semantics captured with a Harnessed tool registration."""

    kind: ActionKind
    chainable: bool = False


def browser_tool[F: Callable[..., object]](
    *,
    description: str,
    kind: ActionKind,
    enabled: bool | Callable[..., bool] = True,
    readonly: bool = False,
    chainable: bool = False,
) -> Callable[[F], F]:
    """Declare a sequential browser tool; a fresh model decision follows by default."""
    return tool(
        description=description,
        enabled=enabled,
        readonly=readonly,
        metadata=(BrowserToolMetadata(chainable=chainable, kind=kind),),
        chain=ToolChain.CONTINUE if chainable else ToolChain.STOP_AFTER,
    )
