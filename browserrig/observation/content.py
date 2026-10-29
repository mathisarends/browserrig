import asyncio
import re
from importlib.resources import files

from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.config import Options
from browserrig.browser.errors import BrowserError
from browserrig.browser.tab import Frame, Tab

from .dom import seed_dom

_CONTENT_SCRIPT = (
    files("browserrig.observation").joinpath("scripts/content.js").read_text(encoding="utf-8")
)


def _heading(text: str) -> str:
    return re.sub(r"([\\`*_[\]<>#])", r"\\\1", " ".join(text.split()))


def _source(url: str) -> str:
    return url.replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")


class _Extraction(Options):
    url: str
    title: str
    markdown: str
    truncated: bool = False
    frames: int = 0


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


async def _seed(
    frame: Frame, metadata: dict[str, CaptureSnapshotResult | None], limitations: list[str]
) -> None:
    await frame.evaluate("globalThis.__browserrigDOM = null")
    try:
        session_id = frame.cdp.session_id
        if session_id not in metadata:
            metadata[session_id] = None
            async with asyncio.timeout(2):
                metadata[session_id] = await frame.cdp.dom_snapshot.capture_snapshot(
                    computed_styles=[]
                )
        snapshot = metadata[session_id]
        if snapshot is None or not await seed_dom(frame, snapshot):
            limitations.append(f"Supplementary DOM metadata incomplete for frame {frame.id}")
    except (CDPCommandError, TimeoutError):
        limitations.append(f"Supplementary DOM metadata unavailable for frame {frame.id}")


async def extract_content(browser: Browser, tab: Tab, *, max_chars: int = 50000) -> PageContent:
    """Read loaded document content without scrolling or replacing interactive element refs."""
    if not 1 <= max_chars <= 200000:
        raise ValueError("max_chars must be between 1 and 200000")
    if tab.dialog:
        raise BrowserError("Handle the open dialog before extracting page content")
    await tab.main_frame()
    document_id = tab.document_id
    frames = await browser.frames(tab)
    limitations = list(tab.frame_limitations)
    metadata: dict[str, CaptureSnapshotResult | None] = {}
    main: _Extraction | None = None
    parts: list[str] = []
    remaining = max_chars
    embedded = 0
    for frame in frames:
        if remaining <= 0:
            limitations.append("Page content was truncated by max_chars")
            break
        try:
            await _seed(frame, metadata, limitations)
            state = _Extraction.model_validate(await frame.call(_CONTENT_SCRIPT, remaining))
            embedded += state.frames
            if main is None:
                main = state
            part = state.markdown
            if frame.parent is not None:
                part = (
                    f"## Frame: {_heading(state.title) or 'Embedded document'}\n\n"
                    f"Source: <{_source(state.url)}>\n\n{part}"
                )
            separator = "\n\n" if parts else ""
            part = separator + part
            if state.truncated or len(part) > remaining:
                limitations.append(
                    "Page content was truncated by max_chars or DOM traversal limits"
                )
            parts.append(part[:remaining])
            remaining -= len(parts[-1])
        except (CDPCommandError, BrowserError, TimeoutError):
            if frame.parent is None:
                raise
            limitations.append(f"Frame {frame.id} changed or could not be inspected")
    if embedded > len(frames) - 1:
        limitations.append("Some embedded frames are unavailable or could not be inspected")
    await tab.main_frame()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during extraction; extract the current page again")
    assert main is not None
    return PageContent(
        url=main.url,
        title=main.title,
        markdown="".join(parts).strip(),
        limitations=tuple(dict.fromkeys(limitations)),
    )
