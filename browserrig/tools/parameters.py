from typing import Annotated

from harnessed import ToolError, ToolParameter
from harnessed.kernel import Inject
from pydantic import Field

from browserrig.browser import Tab, TabPolicy
from browserrig.observation import DomElementHandle, ResolveDomElement


def supports_new_tabs(policy: Inject[TabPolicy | None]) -> bool:
    return policy is None or policy.multiple


def supports_dom_refs(resolver: Inject[ResolveDomElement | None]) -> bool:
    return resolver is not None


async def resolve_dom_element(
    resolver: ResolveDomElement | None, tab: Tab, ref: str
) -> DomElementHandle:
    if resolver is None:
        raise ToolError("This session has no DOM element resolver")
    return await resolver(tab, ref)


type NewTab = Annotated[
    bool,
    Field(description="Open and activate a new tab instead."),
    ToolParameter(enabled=supports_new_tabs),
]
