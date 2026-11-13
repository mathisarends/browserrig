from dataclasses import replace
from typing import Protocol

from harnessed import ToolInfo, ToolResult, ToolStatus

from browserrig.browser import Tab
from browserrig.core import BrowserToolMetadata, ReadinessStatus
from browserrig.observation import (
    BrowserPerception,
    DomReferences,
    Snapshot,
    decision_change,
)


class ActionChainPolicy(Protocol):
    def instructions(self) -> str: ...

    async def check(self, observe: BrowserPerception, tab: Tab) -> str:
        """Empty means continue; otherwise explain why a new observation is needed."""
        ...


class ObserveAfterInput:
    def instructions(self) -> str:
        return "Send one page input at a time, then inspect the next observation before continuing."

    async def check(self, _observe: BrowserPerception, _tab: Tab) -> str:
        return "A fresh observation is required after this input."


class DomActionChains:
    def instructions(self) -> str:
        return (
            "Each response costs a full observation round trip. When the current observation "
            "already shows the refs and values for the next steps, send them as several "
            "ordered tool calls in one response instead of one call per turn. Typical "
            "batches: fill every known form field, then submit; type a search or filter value, "
            "then press Enter or click its search button; set several filters or a page size, "
            "then apply them. Put the call "
            "that submits or navigates last. Navigation, tab changes, scrolling, drags, "
            "coordinates, JavaScript, uploads, dialogs, waiting and screenshots end the "
            "remaining chain; send coordinate actions alone. A navigation, new menu, "
            "suggestions, modal, alert or input failure interrupts the remaining actions; "
            "skipped calls were not executed, so send them again only if still needed. Inspect "
            "the next observation before continuing."
        )

    async def check(self, observe: BrowserPerception, tab: Tab) -> str:
        if not isinstance(observe.references, DomReferences):
            return "A fresh observation is required after this input."
        return await probe_change(observe, tab)


async def probe_change(observe: BrowserPerception, tab: Tab) -> str:
    before = observe.snapshot
    if before is None:
        return "A fresh observation is required after this input."
    after = await observe.probe(tab)
    if after.readiness != ReadinessStatus.READY or after.limitations:
        return "The page could not be checked completely after input."
    return decision_change(
        before, after, dom=isinstance(observe.references, DomReferences)
    )


def stop_on_failure(result: ToolResult, tool: ToolInfo | None) -> ToolResult:
    metadata = tool.metadata.get(BrowserToolMetadata) if tool else None
    # Calls denied, disabled or skipped before execution retain native approval semantics.
    if (
        metadata is not None
        and result.is_error
        and result.status
        not in {ToolStatus.DENIED, ToolStatus.UNAVAILABLE, ToolStatus.SKIPPED}
    ):
        return replace(result, break_chain=True)
    return result


def observes(snapshot: Snapshot, tab: Tab) -> bool:
    return snapshot.tab_id == tab.id and snapshot.document_id == tab.document_id
