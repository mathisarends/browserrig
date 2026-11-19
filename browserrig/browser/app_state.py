from typing import Protocol

from browserrig.core import Generation

from .tab import Tab


class AppState(Protocol):
    """Optional session service for an application's state and input availability."""

    async def generation(self, tab: Tab) -> Generation:
        """Return the application's current target and coordinate identities."""

    async def blocked(self, tab: Tab) -> str | None:
        """Return the reason the app cannot accept input, or None when it can."""


async def read_generation(tab: Tab, app_state: AppState | None) -> Generation:
    if app_state is None:
        return dom_generation(tab)
    app = await app_state.generation(tab)
    dom = dom_generation(tab)
    return Generation(state=(dom.state, app.state), layout=(dom.layout, app.layout))


def dom_generation(tab: Tab) -> Generation:
    return Generation(
        state=tab.document_id, layout=(tab.viewport_revision, tab.layout_revision)
    )


async def blocked_reason(tab: Tab, app_state: AppState | None) -> str | None:
    if tab.dialog is not None:
        return "A JavaScript dialog must be handled first"
    return await app_state.blocked(tab) if app_state is not None else None
