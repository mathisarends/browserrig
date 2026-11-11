from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from harnessed import Plugin, SessionLog
from harnessed.kernel import Event, PluginScope, needs, observes
from pydantic import SecretStr

from browserrig.core import ActionContext, ChangeTab, TargetId
from browserrig.events import BROWSER_EVENTS
from browserrig.files import FileBridge, MountedWorkspace
from browserrig.input import InputTargets

from .base import Browser, BrowserEvents
from .chrome import ChromeBrowser
from .config import BrowserOptions, Connect, Launch, Viewport
from .policy import NavigationPolicy
from .setup import SessionSetup
from .tab import Tab


class Chrome(Plugin, slot="browserrig.browser"):
    """Configure Chrome; each session opens and closes its own browser connection."""

    events = BROWSER_EVENTS
    _log = needs(SessionLog)
    _navigation = observes(NavigationPolicy)
    _actions = needs(ActionContext)

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
        bridge: FileBridge | None = None,
    ) -> Self:
        """Configure a process started at session entry and stopped at session exit.

        Chrome runs on this machine, so it reads a local workspace directly; pass a
        `bridge` for a workspace it cannot see. This call validates configuration
        without starting Chrome. Use the returned plugin as `Agent(browser=...)` or
        in `plugins=[...]`.
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
                bridge=bridge if bridge is not None else MountedWorkspace(),
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
        bridge: FileBridge | None = None,
    ) -> Self:
        """Configure a connection opened at session entry to an existing CDP browser.

        Session exit disconnects without stopping the external process. By default
        a fresh isolated context is created; `target_id` selects an existing tab.
        Chrome runs elsewhere, so it reaches the agent's workspace only through a
        `bridge`; without one, downloads stay on its host and the agent cannot open
        or upload workspace files. This call validates configuration without
        connecting.
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
                bridge=bridge,
            )
        )

    async def setup(self, scope: PluginScope) -> None:
        async def tab_changed(tab: Tab, settled: bool) -> None:
            await scope.dispatch(TabChanged(tab, settled))

        async def change_tab(
            event: ChangeTab, operation: Callable[[], Awaitable[None]]
        ) -> None:
            await scope.dispatch(event, default=operation)

        browser = await scope.enter(
            ChromeBrowser(
                self.options,
                emit=self._log.emit,
                on_tab_change=tab_changed,
                navigation_policy=self._navigation,
                current_action=lambda: self._actions.action_id,
                change_tab=change_tab,
            )
        )
        scope.provide(Browser, browser)
        scope.provide(BrowserEvents, browser.events)
        scope.provide(InputTargets, browser.input_targets)
        if self.options.bridge is not None:
            scope.provide(FileBridge, self.options.bridge)


@dataclass(frozen=True)
class TabChanged(Event[None]):
    """`tab` may show a new url, title or loading state, or has closed.

    `settled` marks a page that stopped loading, so its document can be read.
    """

    tab: Tab
    settled: bool
