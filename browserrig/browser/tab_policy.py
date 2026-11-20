from dataclasses import dataclass

from harnessed import Plugin, SystemPrompt
from harnessed.kernel import PluginScope
from harnessed.prompts import Instructions

from browserrig.core import BrowserError


@dataclass(frozen=True, slots=True)
class TabPolicy:
    """The session's tab capability, available before its browser starts."""

    multiple: bool = True

    def check_new_tab(self) -> None:
        if not self.multiple:
            raise BrowserError("New tabs are unavailable in single-tab mode")


class SingleTab(Plugin, slot="browserrig.tabs", provides=TabPolicy):
    """Keep navigation in the session's sole controlled tab."""

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(TabPolicy, TabPolicy(multiple=False))

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Single browser tab",
                text=(
                    "This session uses one browser tab. Links and file previews replace "
                    "its current page; use browser history to return. Page requests for "
                    "another tab are routed into this tab when supported. A popup that "
                    "requires a separate window is unavailable."
                ),
            )
        )


class MultiTab(Plugin, slot="browserrig.tabs", provides=TabPolicy):
    """Allow the session to open and control multiple tabs."""

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(TabPolicy, TabPolicy())

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Multiple browser tabs",
                text=(
                    "When an input offers new_tab, set it to true to keep the current "
                    "page open. Tabs opened by clicks become active."
                ),
            )
        )
