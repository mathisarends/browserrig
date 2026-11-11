import hashlib
from typing import Literal

from harnessed import Plugin, PluginState, hook
from harnessed.events import ObservationsIncludedEvent
from harnessed.hooks import Next
from harnessed.kernel import needs
from harnessed.models import UserMessage

from .delta import delta, unmarked
from .hooks import ProjectObservation
from .models import Snapshot
from .plugin import BrowserPerception
from .state import TextState


class TextContext(Plugin, slot="browserrig.text"):
    """Publish full observations or retained-base deltas; register no tools."""

    _state = PluginState(TextState)
    _observe = needs(BrowserPerception)

    def __init__(self, *, mode: Literal["delta", "full"] = "delta") -> None:
        super().__init__()
        if mode not in ("delta", "full"):
            raise ValueError("Text context mode must be 'delta' or 'full'")
        self.mode = mode

    @hook(ProjectObservation)
    async def _project(
        self, event: ProjectObservation, next_: Next[UserMessage | None]
    ) -> UserMessage | None:
        message = await next_()
        snapshot = event.snapshot
        state = self._state
        if state.generation != self._observe.generation:
            state.bases.clear()
            state.visible = False
            state.generation = self._observe.generation
        key = self._page_key(snapshot)
        if message is None:
            if (
                self.mode == "delta"
                and snapshot.image is None
                and state.visible
                and state.sent_key == key
            ):
                return None
            message = self._observation(snapshot)
        state.sent_key, state.sent_ref, state.visible = key, snapshot.id, False
        return message

    def _observation(self, snapshot: Snapshot) -> UserMessage:
        state = self._state
        message = self._observe.project(snapshot)
        text = message.text
        plain = unmarked(text)
        page = (
            snapshot.tab_id,
            snapshot.document_id,
            snapshot.viewport_revision,
            snapshot.width,
            snapshot.height,
        )
        base = state.bases.get(page)
        if (
            self.mode == "delta"
            and snapshot.image is None
            and base is not None
            and base[1] in state.included
        ):
            changes = delta(base[0], plain)
            if len(changes) <= len(text) // 2:
                return UserMessage(content=changes)
        state.bases[page] = (plain, snapshot.id)
        return message

    @hook(ObservationsIncludedEvent)
    async def _included(self, event: ObservationsIncludedEvent) -> None:
        state = self._state
        refs = {
            ref
            for item in event.observations
            if item.source == "browser"
            for ref in item.refs
        }
        state.visible = state.sent_ref in refs
        state.included = frozenset(refs)
        state.bases = {
            page: base for page, base in state.bases.items() if base[1] in refs
        }

    def _page_key(self, snapshot: Snapshot) -> str:
        elements = tuple(
            element.model_copy(update={"new": False}) if element.new else element
            for element in snapshot.elements
        )
        text = self._observe.project(
            snapshot.model_copy(update={"elements": elements})
        ).text
        return hashlib.sha256(text.encode()).hexdigest()
