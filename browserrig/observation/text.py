import hashlib
from collections.abc import Callable

from harnessed.models import UserMessage

from .config import DomText, DomTextMode
from .delta import delta, unmarked
from .models import Snapshot
from .state import ObservedText, PageView, TextState


def project_text(
    snapshot: Snapshot,
    state: TextState,
    *,
    options: DomText,
    render: Callable[[Snapshot], str],
    generation: int,
    with_image: bool,
) -> UserMessage | None:
    if state.generation != generation:
        state.bases.clear()
        state.visible = False
        state.generation = generation
    text = render(snapshot)
    key = hashlib.sha256(unmarked(text).encode()).hexdigest()
    if (
        not with_image
        and options.mode == DomTextMode.DELTA
        and state.visible
        and state.sent_key == key
    ):
        return None
    state.sent_key, state.sent_ref, state.visible = key, snapshot.id, False
    return _observation(
        snapshot, text, state, full=with_image or options.mode == DomTextMode.FULL
    )


def include_text(state: TextState, refs: frozenset[str]) -> None:
    state.visible = state.sent_ref in refs
    state.included = refs
    state.bases = {page: base for page, base in state.bases.items() if base.ref in refs}


def _observation(
    snapshot: Snapshot, text: str, state: TextState, *, full: bool
) -> UserMessage:
    plain = unmarked(text)
    page = PageView(
        snapshot.tab_id,
        snapshot.document_id,
        snapshot.viewport_revision,
        snapshot.width,
        snapshot.height,
    )
    base = state.bases.get(page)
    if not full and base is not None and base.ref in state.included:
        changes = delta(base.text, plain)
        if len(changes) <= len(text) // 2:
            return UserMessage(content=changes)
    state.bases[page] = ObservedText(plain, snapshot.id)
    return UserMessage(content=text)
