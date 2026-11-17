from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import NamedTuple

from harnessed import Plugin, PluginState, hook
from harnessed.kernel import PluginScope, needs

from browserrig.browser import Browser, Tab, TabChanged
from browserrig.core import BrowserError
from browserrig.events import TAB_STRIP_EVENTS, TabUpdatedEvent

# A slow icon host costs only the strip state, never the session.
_STRIP_SECONDS = 10


class TabStrip(Plugin):
    """Stream what a viewer's tab strip shows: url, title, loading state and favicon.

    Once a page stops loading, its document title and icon are read in the background,
    so a slow icon host never holds up other events. Later in-page title or icon
    changes, as from scripts or single-page apps, are followed without navigation.
    Without this plugin no tab-strip events are emitted and no icons are fetched.
    """

    events = TAB_STRIP_EVENTS
    # Each open tab's strip in this session.
    _strips = PluginState[dict[str, "_Strip"]](dict)
    _browser = needs(Browser)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._stop)
        # Tabs opened before this plugin started show up once, with what they show now.
        with suppress(BrowserError):
            tab = self._browser.active_tab
            await self._changed(tab, settled=not tab.loading)

    @hook(TabChanged)
    async def _on_change(self, event: TabChanged) -> None:
        await self._changed(event.tab, settled=event.settled)

    async def _changed(self, tab: Tab, *, settled: bool) -> None:
        if tab.closed:
            if strip := self._strips.pop(tab.id, None):
                strip.cancel()
            return
        strip = self._strips.setdefault(tab.id, _Strip())
        await strip.publish(tab)
        if settled:
            strip.cancel()
            strip.task = asyncio.create_task(
                strip.read(tab), name=f"browserrig:tab-strip:{tab.id}"
            )

    async def _stop(self) -> None:
        tasks = [strip.task for strip in self._strips.values() if strip.task]
        for strip in self._strips.values():
            strip.cancel()
        self._strips.clear()
        await asyncio.gather(*tasks, return_exceptions=True)


class _Strip:
    """Own one tab's cached presentation and its cancellable background read."""

    def __init__(self) -> None:
        self._title = ""
        # A newly reported Chrome title replaces the last document-read title.
        self._chrome_title = ""
        self._icon_url = ""
        self._favicon = ""
        self._shown: _StripState | None = None
        self.task: asyncio.Task[None] | None = None

    async def read(self, tab: Tab) -> None:
        try:
            async with asyncio.timeout(_STRIP_SECONDS):
                if tab.dialog is None:
                    strip = await tab.read_strip()
                    # Chrome's target info often keeps the host as title; the document knows.
                    self._title = strip.title or self._title
                    if strip.icon != self._icon_url:
                        # The title should not wait for the icon.
                        await self.publish(tab)
                        favicon = await tab.load_icon(strip.icon) if strip.icon else ""
                        # An interrupted load must be retried on the next strip read.
                        self._icon_url = strip.icon
                        self._favicon = favicon
                await self.publish(tab)
        except Exception:  # pylint: disable=broad-exception-caught
            # Navigation, dialogs and detached sessions only cost the strip state.
            return

    async def publish(self, tab: Tab) -> None:
        """Emit the strip state, once per distinct state."""
        if tab.title != self._chrome_title:
            self._chrome_title = tab.title
            self._title = tab.title
        state = _StripState(tab.url, self._title, tab.loading, self._favicon)
        if tab.closed or state == self._shown:
            return
        self._shown = state
        await tab.emit(
            TabUpdatedEvent(
                url=tab.url,
                title=self._title,
                loading=tab.loading,
                favicon=self._favicon,
            )
        )

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.task = None


class _StripState(NamedTuple):
    url: str
    title: str
    loading: bool
    favicon: str
