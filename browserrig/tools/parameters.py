import logging
from typing import Annotated

from harnessed import ToolError, ToolParameter
from harnessed.kernel import Inject, PluginScope
from pydantic import Field

from browserrig.browser import TabPolicy
from browserrig.dom import ResolveDomElement

logger = logging.getLogger(__name__)


def supports_new_tabs(policy: Inject[TabPolicy | None]) -> bool:
    return policy is None or policy.multiple


def supports_dom_refs(resolver: Inject[ResolveDomElement | None]) -> bool:
    return resolver is not None


def log_missing_dom_refs(scope: PluginScope, plugin_name: str) -> None:
    if ResolveDomElement not in scope:
        logger.debug(
            "%s: tools that require DOM refs are unavailable without ResolveDomElement",
            plugin_name,
        )


def require_dom_resolver(resolver: ResolveDomElement | None) -> ResolveDomElement:
    if resolver is None:
        raise ToolError("This session has no DOM element resolver")
    return resolver


type NewTab = Annotated[
    bool,
    Field(description="Open and activate a new tab instead."),
    ToolParameter(enabled=supports_new_tabs),
]
