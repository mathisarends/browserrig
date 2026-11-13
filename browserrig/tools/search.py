from functools import partial
from typing import Annotated

from harnessed import Plugin, ToolError, ToolResult
from harnessed.kernel import needs, observes
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind, BrowserCoordination, ReadinessStatus
from browserrig.core import browser_tool as tool
from browserrig.observation import PageSearch, extract_document, search_content
from browserrig.readiness import Readiness
from browserrig.secrets import Secrets

from .execution import Actions
from .intents import SearchIntent

type _Query = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description="Literal text, ignoring case and accents.",
    ),
]


class PageSearchTools(Plugin):
    """Search loaded page text and return matching records without changing the page."""

    _browser = needs(Browser)
    _coordination = needs(BrowserCoordination)
    _readiness = needs(Readiness)
    _secrets = observes(Secrets)
    # Lets viewers watch the search in the find bar.
    _actions = observes(Actions)

    @tool(
        kind=ActionKind.SEARCH_PAGE,
        readonly=True,
        chainable=True,
        description=(
            "Search the loaded page; return matching table rows, list items and "
            "paragraphs with their column headers and links."
        ),
    )
    async def search_page(
        self,
        query: _Query,
        alternatives: Annotated[
            tuple[_Query, ...],
            Field(max_length=4, description="Other wordings; a record may match any."),
        ] = (),
        full_page: Annotated[
            bool, Field(description="Also search site header, navigation and footer.")
        ] = False,
        start: Annotated[
            int, Field(ge=0, description="Matching records to skip, to continue.")
        ] = 0,
        max_results: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> ToolResult:
        queries = tuple(
            dict.fromkeys(" ".join(text.split()) for text in (query, *alternatives))
        )
        if not all(queries):
            raise ToolError("query and alternatives must contain visible text")
        tab = self._browser.active_tab
        step = partial(
            self._search,
            tab,
            queries,
            full_page=full_page,
            start=start,
            count=max_results,
        )
        actions = self._actions
        if actions is None:
            found = await step()
        else:
            found = await actions.stage(SearchIntent(queries), tab, step)
        return ToolResult(found.render())

    async def _search(
        self,
        tab: Tab,
        queries: tuple[str, ...],
        *,
        full_page: bool,
        start: int,
        count: int,
    ) -> PageSearch:
        async with self._coordination.exclusive():
            report = await self._readiness.wait(tab)
            if report.status == ReadinessStatus.BLOCKED:
                raise ToolError(report.reason)
            content = await extract_document(tab, full_page=full_page)
        if (secrets := self._secrets) is not None:
            content = secrets.redact(content)
        try:
            return search_content(content, queries, start=start, count=count)
        except ValueError as error:
            raise ToolError(str(error)) from error
