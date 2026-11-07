from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from harnessed import Plugin, SessionLog
from harnessed.kernel import Event, Scope, needs
from pydantic import SecretStr

from browserrig.core import TargetId
from browserrig.events import BROWSER_EVENTS
from browserrig.files import FileSystemOptions

from .base import Browser, BrowserEvents
from .chrome import ChromeBrowser
from .config import BrowserOptions, Connect, Launch, Viewport
from .setup import SessionSetup
from .tab import Tab


class Chrome(Plugin, slot="browserrig.browser"):
    """Configure Chrome; each session opens and closes its own browser connection."""

    events = BROWSER_EVENTS
    _log = needs(SessionLog)

    def __init__(self, options: BrowserOptions | None = None) -> None:
        super().__init__()
        self.options = options if options is not None else Launch()

    @classmethod
    def launch(
        cls,
        *,
        executable: Path | None = None,
        headless: bool = True,
        url: str = "about:blank",
        viewport: Viewport | None = None,
        session_setup: tuple[SessionSetup, ...] = (),
        timeout: float = 20,
        arguments: tuple[str, ...] = (),
        download_directory: str | None = None,
        files: FileSystemOptions | None = None,
    ) -> Self:
        """Configure a process started at session entry and stopped at session exit.

        This call validates configuration without starting Chrome or creating files.
        Use the returned plugin as `Agent(browser=...)` or in `plugins=[...]`.
        """
        return cls(
            Launch(
                executable=executable,
                headless=headless,
                url=url,
                viewport=viewport if viewport is not None else Viewport(),
                session_setup=session_setup,
                timeout=timeout,
                arguments=arguments,
                download_directory=download_directory,
                files=files if files is not None else FileSystemOptions(),
            )
        )

    @classmethod
    def connect(
        cls,
        *,
        endpoint: str | SecretStr,
        target_id: TargetId | None = None,
        url: str = "about:blank",
        timeout: float = 20,
        headers: Mapping[str, str | SecretStr] | None = None,
        viewport: Viewport | None = None,
        session_setup: tuple[SessionSetup, ...] = (),
        download_directory: str | None = None,
        files: FileSystemOptions | None = None,
    ) -> Self:
        """Configure a connection opened at session entry to an existing CDP browser.

        Session exit disconnects without stopping the external process. By default
        a fresh isolated context is created; `target_id` selects an existing tab.
        This call validates configuration without connecting or creating files.
        """
        return cls(
            Connect(
                endpoint=SecretStr(endpoint) if isinstance(endpoint, str) else endpoint,
                target_id=target_id,
                url=url,
                timeout=timeout,
                headers={
                    key: SecretStr(value) if isinstance(value, str) else value
                    for key, value in (headers.items() if headers is not None else ())
                },
                viewport=viewport,
                session_setup=session_setup,
                download_directory=download_directory,
                files=files,
            )
        )

    async def setup(self, ctx: Scope) -> None:
        async def tab_changed(tab: Tab, settled: bool) -> None:
            await ctx.dispatch(TabChanged(tab, settled))

        browser = await ctx.enter(
            ChromeBrowser(
                self.options,
                emit=self._log.emit,
                on_tab_change=tab_changed,
            )
        )
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)


@dataclass(frozen=True)
class TabChanged(Event[None]):
    """`tab` may show a new url, title or loading state, or has closed.

    `settled` marks a page that stopped loading, so its document can be read.
    """

    tab: Tab
    settled: bool
