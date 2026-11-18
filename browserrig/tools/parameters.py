from typing import Annotated

from harnessed import ToolParameter
from harnessed.kernel import Inject
from pydantic import Field

from browserrig.browser import TabPolicy


def supports_new_tabs(policy: Inject[TabPolicy | None]) -> bool:
    return policy is None or policy.multiple


type NewTab = Annotated[
    bool,
    Field(description="Open and activate a new tab instead."),
    ToolParameter(enabled=supports_new_tabs),
]
