import asyncio
from typing import Annotated
from uuid import uuid4

from harnessed import Inject, Plugin, ToolError, ToolResult
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core.kinds import ActionKind, BrowserBar
from browserrig.core.tools import browser_tool as tool
from browserrig.events import FindBarEvent, FindResultsEvent
from browserrig.observation.find import FoundMatch, PageMatches, close_find, find_text

from .execution import Actions, Effect

# How long viewers see the final results before the find bar closes.
_HOLD_SECONDS = 0.6
# Alternatives appear in the find bar joined by this, typed like one text.
_OR = " | "

type _Query = Annotated[str, Field(min_length=1, max_length=200)]


class FindTools(Plugin, needs=(Actions, Browser)):
    """Search the page's text the way a person uses the browser's find bar."""

    _browser: Inject[Browser]

    @tool(
        kind=ActionKind.FIND_IN_PAGE,
        description=(
            "Find text on the page like Ctrl+F, ignoring case and accents, across frames and "
            "collapsed sections. Lists matches with their context and nearest heading, and "
            "scrolls match number `match` into view, opening a collapsed section around it. "
            "Use it to locate something on a long page without reading all of it. Give "
            "alternatives such as synonyms, other spellings or languages to search them in the "
            "same call; their matches are numbered together in page order."
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
        match: Annotated[int, Field(ge=1)] = 1,
        max_results: Annotated[int, Field(ge=1, le=50)] = 10,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        queries = tuple(
            dict.fromkeys(" ".join(text.split()) for text in (query, *alternatives))
        )
        if not all(queries):
            raise ToolError("query and alternatives must contain visible text")
        shown = _OR.join(queries)
        inputs = self._browser.input

        async def find(tab: Tab) -> Effect:
            session = uuid4().hex

            async def preview(typed: str) -> None:
                # Like a browser's find bar: results follow each key, without scrolling.
                if typing := _typed(queries, len(typed)):
                    found = await find_text(tab, typing, session=session)
                    await inputs.announce(tab, _results(typed, found, current=1))

            await inputs.keyboard.show_key(tab, "f", hold_control=True)
            await inputs.announce(tab, FindBarEvent(visible=True))
            try:
                await inputs.type_in_bar(tab, BrowserBar.FIND, shown, after_key=preview)
                found = await find_text(
                    tab,
                    queries,
                    session=session,
                    active=match - 1,
                    start=match - 1,
                    count=max_results,
                    reveal=True,
                )
                await inputs.announce(tab, _results(shown, found, current=match))
                await asyncio.sleep(_HOLD_SECONDS)
                return Effect(_report(queries, match, found), prepared_scroll=True)
            finally:
                await inputs.keyboard.show_key(tab, "Escape")
                await close_find(tab)
                await inputs.announce(tab, FindBarEvent(visible=False))

        return await actions.run(kind=ActionKind.FIND_IN_PAGE, operation=find)


def _results(query: str, found: PageMatches, *, current: int) -> FindResultsEvent:
    return FindResultsEvent(
        query=query,
        total=found.total,
        active=current if current <= found.total else 0,
        marks=found.marks,
    )


def _typed(queries: tuple[str, ...], length: int) -> tuple[str, ...]:
    """The alternatives typed so far once the find bar holds `length` characters."""
    typed = []
    position = 0
    for query in queries:
        if position >= length:
            break
        typed.append(query[: length - position].strip())
        position += len(query) + len(_OR)
    return tuple(query for query in typed if query)


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
            "shorter or different wording, or extract_content to read the page."
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
