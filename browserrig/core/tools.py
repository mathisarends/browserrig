from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from inspect import iscoroutinefunction, signature
from typing import Annotated, cast
from weakref import WeakKeyDictionary

from harnessed import tool
from harnessed.kernel import PluginBase, Scope, Waterfall, registration
from harnessed.tools import ToolChain, ToolInfo
from pydantic import Field

from .kinds import ActionKind
from .options import Options


class ActionLabel(Options):
    """Optional model-written display text for a tool call's envelope."""

    action_label: Annotated[
        str,
        Field(
            min_length=1,
            max_length=80,
            pattern=r"\S",
            description=(
                "Short human-readable action in progress, such as 'Opening the pricing page'. "
                "Describe intent without credentials, personal data or other sensitive values."
            ),
        ),
    ]


@dataclass(frozen=True, slots=True)
class BrowserToolMetadata:
    """Process-local browser semantics captured with a Harnessed tool registration."""

    kind: ActionKind
    chainable: bool = False


@dataclass(frozen=True)
class BrowserToolCall(Waterfall[object]):
    """Run a browser tool's body before Harnessed converts its return value."""

    metadata: BrowserToolMetadata
    arguments: Mapping[str, object]
    name: str = ""


def is_javascript_tool(name: str, info: ToolInfo | None) -> bool:
    """Recognize the JavaScript action and older registrations used by guards."""
    if name == "execute_javascript":
        return True
    if info is None:
        return False
    metadata = info.metadata.get(BrowserToolMetadata)
    return info.matches(ActionKind.JAVASCRIPT) or (
        metadata is not None and metadata.kind == ActionKind.JAVASCRIPT
    )


def browser_tool[F: Callable[..., Awaitable[object]]](
    *,
    description: str,
    kind: ActionKind,
    enabled: bool | Callable[..., bool] = True,
    readonly: bool = False,
    chainable: bool = False,
) -> Callable[[F], F]:
    """Declare an async browser tool coordinated by the Actions plugin.

    Synchronous callbacks are rejected rather than bypassing browser coordination.
    """
    metadata = BrowserToolMetadata(chainable=chainable, kind=kind)
    register = tool(
        action=kind,
        description=description,
        enabled=enabled,
        readonly=readonly,
        metadata=(metadata,),
        chain=ToolChain.CONTINUE if chainable else ToolChain.STOP_AFTER,
    )

    def decorate(callback: F) -> F:
        if not iscoroutinefunction(callback):
            raise TypeError(
                "browser_tool requires an async function; mark a synchronous wrapper "
                "that returns a coroutine with inspect.markcoroutinefunction"
            )
        binding = _ToolBinding()
        parameters = signature(callback)
        name = getattr(callback, "__name__", "")

        @wraps(callback)
        async def execute(*args, **kwargs):
            owner = args[0] if args else None
            scope = (
                binding.scopes.get(owner)
                if isinstance(owner, PluginBase)
                else Scope.current()
            )

            async def perform():
                return await callback(*args, **kwargs)

            if scope is None:
                return await perform()
            arguments = parameters.bind(*args, **kwargs)
            arguments.apply_defaults()
            return await scope.dispatch(
                BrowserToolCall(metadata, arguments.arguments, name),
                default=perform,
            )

        return registration(binding)(register(cast(F, execute)))

    return decorate


class _ToolBinding:
    """Associate mounted methods with their owner scope, including direct calls."""

    needs = ()  # smelt: ignore[SMT335] -- Harnessed's Registration protocol reads this attribute.

    def __init__(self) -> None:
        self.scopes: WeakKeyDictionary[PluginBase, Scope] = WeakKeyDictionary()

    def mount(self, scope: Scope, callback: Callable) -> None:
        owner = getattr(callback, "__self__", None)
        if owner is not None:
            self.scopes[owner] = scope
            scope.effect(lambda: self.scopes.pop(owner, None))
