import re
from urllib.parse import urljoin, urlsplit

from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.exceptions import CDPCommandError

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.options import Options
from browserrig.scripts import CONTENT
from browserrig.scripts.models import ContentArgs, ContentExtraction

from .dom import seed_frame
from .redirects import unwrap_redirect

_LINK = re.compile(r"\]\(<([^<>\s]+)>\)")


class PageContent(Options):
    url: str
    title: str
    markdown: str
    limitations: tuple[str, ...] = ()

    def render(self) -> str:
        text = f"# {_heading(self.title) or 'Page content'}\n\nSource: <{_source(self.url)}>"
        if self.markdown:
            text += f"\n\n{self.markdown}"
        if self.limitations:
            text += "\n\n> Extraction limitations:\n" + "\n".join(
                f"> - {item}" for item in self.limitations
            )
        return text


async def extract_content(
    tab: Tab, *, max_chars: int = 50000, full_page: bool = False
) -> PageContent:
    """Read loaded document content without scrolling or replacing interactive element refs.

    Unless ``full_page`` is set, a page's main landmark replaces its surrounding header,
    navigation and footer. Links on the page's own origin are shortened to paths.
    """
    if not 1 <= max_chars <= 200000:
        raise ValueError("max_chars must be between 1 and 200000")
    if tab.dialog:
        raise BrowserError("Handle the open dialog before extracting page content")
    await tab.sync_document()
    document_id = tab.document_id
    url = urlsplit(tab.url)
    origin = f"{url.scheme}://{url.netloc}" if url.scheme in {"http", "https"} else ""

    def args(budget: int) -> ContentArgs:
        return ContentArgs(max_chars=budget, main_only=not full_page, origin=origin)

    frames = await tab.frames()
    limitations = list(tab.frame_limitations)
    metadata: dict[str, CaptureSnapshotResult | None] = {}
    main: ContentExtraction | None = None
    parts: list[str] = []
    remaining = max_chars
    embedded = 0
    for frame in frames:
        if remaining <= 0:
            limitations.append("Page content was truncated by max_chars")
            break
        try:
            await seed_frame(frame, metadata, limitations)
            state = await frame.run(CONTENT, args(remaining))
            embedded += state.frames
            main = main or state
            prefix = "\n\n" if parts else ""
            if frame.parent is not None:
                prefix += (
                    f"## Frame: {_heading(state.title) or 'Embedded document'}\n\n"
                    f"Source: <{_source(state.url)}>\n\n"
                )
            available = max(0, remaining - len(prefix))
            body = state.markdown
            if state.truncated or len(body) > available:
                limitations.append(
                    "Page content was truncated by max_chars or DOM traversal limits"
                )
            if len(body) > available:
                # Let the script close code fences using the actual body budget.
                body = (await frame.run(CONTENT, args(available))).markdown if available else ""
            parts.append(prefix[:remaining] + _unwrap_links(body, state.url, origin))
            remaining -= len(parts[-1])
        except (CDPCommandError, BrowserError, TimeoutError):
            if frame.parent is None:
                raise
            limitations.append(f"Frame {frame.id} changed or could not be inspected")
    if embedded > len(frames) - 1:
        limitations.append("Some embedded frames are unavailable or could not be inspected")
    await tab.sync_document()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during extraction; extract the current page again")
    assert main is not None
    if main.main:
        limitations.insert(
            0,
            "Only the main region is included; header, navigation and footer were omitted "
            "(full_page=true includes them)",
        )
    return PageContent(
        url=main.url,
        title=main.title,
        markdown="".join(parts).strip(),
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _heading(text: str) -> str:
    return re.sub(r"([\\`*_[\]<>#])", r"\\\1", " ".join(text.split()))


def _unwrap_links(markdown: str, base: str, origin: str) -> str:
    """Replace search-engine tracking links with the destinations they redirect to."""

    def replace(match: re.Match[str]) -> str:
        href = urljoin(base, match.group(1))
        target = unwrap_redirect(href)
        if target == href:
            return match.group(0)
        if origin and target.startswith(origin + "/"):
            target = target[len(origin) :]
        return f"](<{_source(target)}>)"

    return _LINK.sub(replace, markdown)


def _source(url: str) -> str:
    return url.replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")
