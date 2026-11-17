from typing import Annotated

from harnessed.kernel import Inject
from pydantic import Field

from browserrig.browser import TabPolicy


def supports_new_tabs(policy: Inject[TabPolicy | None]) -> bool:
    return policy is None or policy.multiple


# Add ToolParameter(enabled=supports_new_tabs) when harnessed#120 is available.
# Keep the ordinary argument type until then; do not emulate it in PrepareRequest.
type NewTab = Annotated[bool, Field(description="Open and activate a new tab instead.")]
