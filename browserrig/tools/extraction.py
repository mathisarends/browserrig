from dataclasses import dataclass

from harnessed import Plugin, PluginState, ToolError, ToolResult
from harnessed.kernel import Event, PluginScope, needs, observes

from browserrig.browser import Browser
from browserrig.core import ActionKind, BrowserCoordination, ReadinessStatus
from browserrig.core import browser_tool as tool
from browserrig.files import FileSystem
from browserrig.observation import ExtractedContent, extract_document, save_content
from browserrig.readiness import Readiness
from browserrig.secrets import Secrets


@dataclass(frozen=True)
class PageContentExtracted(Event[None]):
    """A redacted saved extraction, available to optional presentation observers."""

    target_id: str
    document_id: str
    content: ExtractedContent


@dataclass
class _Extraction:
    context: PluginScope | None = None
    content: ExtractedContent | None = None


class PageExtractionTools(Plugin, provides=True):
    """Save loaded DOM content to an explicit workspace; preserve live observation refs."""

    _state = PluginState(_Extraction)
    _browser = needs(Browser)
    _coordination = needs(BrowserCoordination)
    _readiness = needs(Readiness)
    _workspace = needs(FileSystem)
    _secrets = observes(Secrets)

    async def setup(self, scope: PluginScope) -> None:
        self._state.context = scope

    @property
    def extracted_content(self) -> ExtractedContent | None:
        return self._state.content

    @tool(
        kind=ActionKind.EXTRACT_CONTENT,
        readonly=True,
        chainable=True,
        description=(
            "Save the active page's loaded content as a Markdown snapshot in the workspace. "
            "Returns only Saved, Source, Title and reported extraction limitations, not page text. "
            "Use grep to find text in the saved path and read_file for bounded excerpts. "
            "Includes loaded content below the viewport without navigating. "
            "Uses the main region when available; full_page=true also includes site navigation. "
            "Each call saves a new snapshot. Requires a workspace."
        ),
    )
    async def extract_content(self, full_page: bool = False) -> ToolResult:
        files = self._workspace
        if files is None:
            raise ToolError(
                "Page extraction needs a workspace; configure Files() to save snapshots"
            )
        async with self._coordination.exclusive():
            tab = self._browser.active_tab
            report = await self._readiness.wait(tab)
            if report.status == ReadinessStatus.BLOCKED:
                raise ToolError(report.reason)
            content = await extract_document(tab, full_page=full_page)
            secrets = self._secrets
            if secrets is not None:
                content = secrets.redact(content)
            try:
                saved = await save_content(files, content, full_page=full_page)
            except (OSError, ValueError) as error:
                raise ToolError(
                    f"Page extraction could not be saved: {error}"
                ) from error
            self._state.content = saved
            context = self._state.context
            assert context is not None
            await context.dispatch(PageContentExtracted(tab.id, tab.document_id, saved))
            return ToolResult(saved.render_receipt())
