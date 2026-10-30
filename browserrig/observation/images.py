from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from harnessed import Inject, Plugin, PluginState, SystemSection, hook
from harnessed.hooks import Next, PrepareRequest
from harnessed.models import ImagePart, Message, ModelRequest, TextPart, User

from browserrig.events import ObservationCapturedEvent

from .models import CapturedImage
from .plugin import Observe

# Harnessed names observation messages "observation:{turn}:{step}:{source}:{form}" and keeps
# them at their place in history; only the form suffix changes from "full" to "summary".
_FULL = ":browser:full"
_SUMMARY = ":browser:summary"


@dataclass(frozen=True, slots=True)
class _Anchor:
    """Where an image was first shown: after its browser observation."""

    observation: str  # observation id without the form suffix
    fallback: str  # message before the observation, kept once the observation is dropped


@dataclass
class _State:
    images: list[CapturedImage] = field(default_factory=list)
    anchors: dict[str, _Anchor] = field(default_factory=dict)


class ImageContext(Plugin, needs=(Observe,)):
    """Keep captured images in history where they were taken, trimming them in batches.

    Every image stays at a fixed place with a fixed caption, so the prompt prefix stays
    cacheable. Once more than ``max_images`` are kept, the oldest are dropped until
    ``min_images`` remain. Each trim changes the prefix once instead of on every step.
    """

    _state = PluginState(_State)
    _observe: Inject[Observe]

    usage = SystemSection(
        title="Browser image history",
        text=(
            "Each screenshot appears right after the observation it was captured with and is "
            "labelled with capture time, tab and document. The last line of the context names "
            "the latest screenshot. Coordinate tools use its pixels, including its crop and "
            "zoom, while it shows the current document."
        ),
    )

    def __init__(self, max_images: int = 1, min_images: int | None = None) -> None:
        super().__init__()
        if min_images is None:
            min_images = max(1, max_images // 2) if _positive(max_images) else max_images
        if not _positive(max_images) or not _positive(min_images):
            raise ValueError("max_images and min_images must be positive integers")
        if min_images > max_images:
            raise ValueError("min_images must not exceed max_images")
        self.max_images = max_images
        self.min_images = min_images

    @property
    def images(self) -> tuple[CapturedImage, ...]:
        return tuple(self._state.images)

    @hook(ObservationCapturedEvent)
    async def _captured(self, event: ObservationCapturedEvent) -> None:
        snapshot = self._observe.snapshot
        if snapshot is None or snapshot.id != event.observation_id or snapshot.image is None:
            return
        state = self._state
        if any(image.id == snapshot.id for image in state.images):
            return
        state.images.append(CapturedImage.from_snapshot(snapshot, event.browser_id))
        if len(state.images) > self.max_images:
            for dropped in state.images[: -self.min_images]:
                state.anchors.pop(dropped.id, None)
            del state.images[: -self.min_images]

    @hook(PrepareRequest)
    async def _prepare(self, _event: PrepareRequest, next_: Next[ModelRequest]) -> ModelRequest:
        request = await next_()
        images = self._state.images
        if not images:
            return request
        self._anchor_new_images(request.messages)
        latest = images[-1]
        self._observe.image_delivered(latest)
        messages = (*self._insert_images(request.messages), self._latest_note(latest))
        return replace(request, messages=messages)

    def _anchor_new_images(self, messages: Sequence[Message]) -> None:
        """Pin images seen for the first time to the observation of the current step."""
        anchor = _current_anchor(messages)
        if anchor is not None:
            for image in self._state.images:
                self._state.anchors.setdefault(image.id, anchor)

    def _insert_images(self, messages: Sequence[Message]) -> list[Message]:
        """Place each image right after its anchor; images without one go last."""
        ids = {_observation_key(message) or message.id: message.id for message in messages}
        after: defaultdict[str, list[Message]] = defaultdict(list)
        for image in self._state.images:
            anchor = self._state.anchors.get(image.id)
            target = ""
            if anchor is not None:
                target = ids.get(anchor.observation) or ids.get(anchor.fallback) or ""
            after[target].append(_image_message(image))
        result: list[Message] = []
        for message in messages:
            result.append(message)
            result.extend(after.pop(message.id, ()))
        result.extend(after.pop("", ()))
        return result

    def _latest_note(self, latest: CapturedImage) -> User:
        snapshot = self._observe.snapshot
        text = f"Latest screenshot: {latest.id}"
        if snapshot is None or (latest.tab_id, latest.document_id) != (
            snapshot.tab_id,
            snapshot.document_id,
        ):
            text += " (another document)"
        return User(text, id="browser-latest-image")


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _current_anchor(messages: Sequence[Message]) -> _Anchor | None:
    for index, message in enumerate(messages):
        if message.id.startswith("observation:") and message.id.endswith(_FULL):
            fallback = messages[index - 1].id if index else ""
            return _Anchor(message.id.removesuffix(_FULL), fallback)
    return None


def _observation_key(message: Message) -> str | None:
    """The id part shared by the full and summary form of a browser observation."""
    if message.id.startswith("observation:"):
        for suffix in (_FULL, _SUMMARY):
            if message.id.endswith(suffix):
                return message.id.removesuffix(suffix)
    return None


def _image_message(image: CapturedImage) -> User:
    # The caption never changes, so a delivered image keeps the prompt prefix stable.
    caption = (
        f"Screenshot {image.id}; captured={image.captured_at.isoformat()}; "
        f"browser={image.browser_id}; tab={image.tab_id}; document={image.document_id}"
    )
    if image.geometry is not None:
        caption += f"; geometry={image.geometry.model_dump_json()}"
    return User(
        (TextPart(caption), ImagePart(f"data:image/png;base64,{image.image}")),
        id=f"browser-image:{image.id}",
    )
