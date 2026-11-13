from functools import partial
from typing import Annotated
from uuid import uuid4

from harnessed import Plugin, ToolError
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool
from browserrig.observation import FoundMatch, PageMatches, close_find, find_text

from .effects import Effect
from .execution import Actions
from .intents import FindIntent

type _Query = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description="Text to match, ignoring case and accents.",
    ),
]


class FindTools(Plugin):
    """Search the page's text the way a person uses the browser's find bar."""

    _actions = needs(Actions)

    @tool(
        kind=ActionKind.FIND_IN_PAGE,
        description=(
            "Find page text across frames and collapsed sections; reveal the selected "
            "match."
        ),
    )
    async def find_in_page(
        self,
        query: _Query,
        alternatives: Annotated[
            tuple[_Query, ...],
            Field(
                max_length=4, description="Other wordings searched together with query."
            ),
        ] = (),
        match: Annotated[int, Field(ge=1, description="1-based match to reveal.")] = 1,
        max_results: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> Effect:
        queries = tuple(
            dict.fromkeys(" ".join(text.split()) for text in (query, *alternatives))
        )
        if not all(queries):
            raise ToolError("query and alternatives must contain visible text")

        tab = self._actions.tab
        session = uuid4().hex
        try:
            found = await self._actions.stage(
                FindIntent(queries, match, session),
                tab,
                partial(
                    find_text,
                    tab,
                    queries,
                    session=session,
                    active=match - 1,
                    start=match - 1,
                    count=max_results,
                    reveal=True,
                ),
            )
            return Effect(_report(queries, match, found), prepared_scroll=True)
        finally:
            await close_find(tab)


def _report(queries: tuple[str, ...], match: int, found: PageMatches) -> str:
    if len(queries) == 1:
        quoted = f'"{queries[0]}"'
    else:
        counted = [
            f'"{query}" ({count})'
            for query, count in zip(queries, found.counts, strict=True)
        ]
        quoted = ", ".join(counted[:-1]) + " or " + counted[-1]
    if not found.total:
        lines = [
            f"No matches for {quoted} on the page. Matching ignores case and accents; try a "
            "shorter or different wording, or search_page to read matching records."
        ]
    elif match > found.total:
        lines = [
            f"{_count(found.total)} for {quoted}; there is no match {match}. "
            f"Use match between 1 and {found.total}."
        ]
    else:
        where = "scrolled into view" if found.scrolled else "in view"
        lines = [f"{_count(found.total)} for {quoted}; match {match} is {where}.", ""]
        lines += [_line(item) for item in found.matches]
        last = found.matches[-1].number if found.matches else match - 1
        if last < found.total:
            lines += [
                "",
                f"find_in_page with match={last + 1} lists the following matches.",
            ]
    if found.limitations:
        lines += [
            "",
            "Search limitations:",
            *(f"- {item}" for item in found.limitations),
        ]
    return "\n".join(lines)


def _count(total: int) -> str:
    return "1 match" if total == 1 else f"{total} matches"


def _line(match: FoundMatch) -> str:
    found = match.found
    text = f"{found.before}**{found.text}**{found.after}"
    heading = f"[{found.heading}] " if found.heading else ""
    hidden = " (in a collapsed section)" if found.collapsed else ""
    return f"{match.number}. {heading}{text}{hidden}"
