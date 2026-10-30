from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from harnessed import Inject, Plugin, PluginState, SystemSection, hook
from harnessed.hooks import Next, PrepareRequest
from harnessed.models import ImagePart, Message, ModelRequest, TextPart, User

from browserrig.events import ObservationCapturedEvent

from .models import CapturedImage
from .plugin import Observe

# Harnessed names observation messages "observation:{turn}:{step}:{source}:{form}" and keeps
# them at their place in history; only the form suffix changes from "full" to "summary".
_OBSERVATION = "observation:"
_SUMMARY_PREFIX = "compaction:"
_FULL = ":browser:full"
_SUMMARY = ":browser:summary"


class ImageRetention(Protocol):
    """Decides how many of the oldest images to drop once a new one was added."""

    def overflow(self, count: int) -> int: ...


@dataclass(frozen=True, slots=True, init=False)
class TrimInBatches:
    """Keep at most ``max_images``; on overflow drop the oldest until ``min_images`` remain.

    Each trim changes the prompt prefix once instead of on every step. ``min_images``
    defaults to half of ``max_images`` (at least one).
    """

    max_images: int
    min_images: int

    def __init__(self, max_images: int = 1, min_images: int | None = None) -> None:
        if min_images is None:
            min_images = max(1, max_images // 2) if _positive(max_images) else max_images
        if not _positive(max_images) or not _positive(min_images):
            raise ValueError("max_images and min_images must be positive integers")
        if min_images > max_images:
            raise ValueError("min_images must not exceed max_images")
        object.__setattr__(self, "max_images", max_images)
        object.__setattr__(self, "min_images", min_images)

    def overflow(self, count: int) -> int:
        return count - self.min_images if count > self.max_images else 0


@dataclass(frozen=True, slots=True)
class UntilCompaction:
    """Never trim; images leave history together with the steps compaction summarizes."""

    def overflow(self, count: int) -> int:  # pylint: disable=unused-argument
        return 0


@dataclass(frozen=True, slots=True)
class _Anchor:
    """Where an image was first shown: after its browser observation."""

    observation: str  # observation id without the form suffix
    # The closest earlier conversation message; keeps the place once the observation is gone.
    fallback: str


@dataclass
class _State:
    images: list[CapturedImage] = field(default_factory=list)
    anchors: dict[str, _Anchor] = field(default_factory=dict)
    summary: str | None = None  # id of the latest compaction summary seen in a request


class ImageContext(Plugin, needs=(Observe,)):
    """Keep captured images in history where they were taken.

    Every image stays at a fixed place with a fixed caption, so the prompt prefix stays
    cacheable. ``retention`` decides when the oldest images are dropped. After each
    compaction, images whose observation was summarized are dropped as well, except the
    latest one. With
    ``skip_unchanged``, a capture identical to the latest image is not added again.
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

    def __init__(
        self, retention: ImageRetention | None = None, *, skip_unchanged: bool = True
    ) -> None:
        super().__init__()
        self.retention = retention or TrimInBatches()
        self.skip_unchanged = skip_unchanged

    @property
    def images(self) -> tuple[CapturedImage, ...]:
        return tuple(self._state.images)

    @hook(ObservationCapturedEvent)
    async def _captured(self, event: ObservationCapturedEvent) -> None:
        snapshot = self._observe.snapshot
        if snapshot is None or snapshot.id != event.observation_id or snapshot.image is None:
            return
        images = self._state.images
        if any(image.id == snapshot.id for image in images):
            return
        image = CapturedImage.from_snapshot(snapshot, event.browser_id)
        if self.skip_unchanged and images and _same_screen(images[-1], image):
            return
        images.append(image)
        self._forget(images[: self.retention.overflow(len(images))])

    @hook(PrepareRequest)
    async def _prepare(self, _event: PrepareRequest, next_: Next[ModelRequest]) -> ModelRequest:
        request = await next_()
        if not self._state.images:
            return request
        self._anchor_new_images(request.messages)
        places = _places(request.messages)
        self._forget_compacted(request.messages, places)
        latest = self._state.images[-1]
        self._observe.image_delivered(latest)
        messages = (*self._insert_images(request.messages, places), self._latest_note(latest))
        return replace(request, messages=messages)

    def _anchor_new_images(self, messages: Sequence[Message]) -> None:
        """Pin images seen for the first time to the observation of the current step."""
        anchor = _current_anchor(messages)
        if anchor is not None:
            for image in self._state.images:
                self._state.anchors.setdefault(image.id, anchor)

    def _forget_compacted(self, messages: Sequence[Message], places: dict[str, str]) -> None:
        """After a new compaction summary, drop images whose observation was summarized.

        The latest image stays, because coordinate tools rely on it.
        """
        state = self._state
        summary = next((m.id for m in messages if m.id.startswith(_SUMMARY_PREFIX)), None)
        if summary is None or summary == state.summary:
            return
        state.summary = summary
        self._forget(
            [
                image
                for image in state.images[:-1]
                if (anchor := state.anchors.get(image.id)) is not None
                and anchor.observation not in places
            ]
        )

    def _forget(self, dropped: Sequence[CapturedImage]) -> None:
        ids = {image.id for image in dropped}
        if ids:
            self._state.images[:] = [image for image in self._state.images if image.id not in ids]
            for image_id in ids:
                self._state.anchors.pop(image_id, None)

    def _insert_images(self, messages: Sequence[Message], places: dict[str, str]) -> list[Message]:
        """Place each image right after its anchor; images without one go last."""
        after: defaultdict[str, list[Message]] = defaultdict(list)
        for image in self._state.images:
            anchor = self._state.anchors.get(image.id)
            target = ""
            if anchor is not None:
                target = places.get(anchor.observation) or places.get(anchor.fallback) or ""
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
        elif snapshot.image is not None and snapshot.id != latest.id:
            # This step captured an image, but it matched the latest one and was not added.
            text += " (screen unchanged this step)"
        return User(text, id="browser-latest-image")


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _same_screen(kept: CapturedImage, new: CapturedImage) -> bool:
    return (kept.tab_id, kept.document_id, kept.geometry, kept.image) == (
        new.tab_id,
        new.document_id,
        new.geometry,
        new.image,
    )


def _places(messages: Sequence[Message]) -> dict[str, str]:
    """Message ids by anchor key; both forms of an observation share one key."""
    return {_observation_key(message) or message.id: message.id for message in messages}


def _current_anchor(messages: Sequence[Message]) -> _Anchor | None:
    for index, message in enumerate(messages):
        if message.id.startswith(_OBSERVATION) and message.id.endswith(_FULL):
            earlier = (
                m.id for m in reversed(messages[:index]) if not m.id.startswith(_OBSERVATION)
            )
            return _Anchor(message.id.removesuffix(_FULL), next(earlier, ""))
    return None


def _observation_key(message: Message) -> str | None:
    """The id part shared by the full and summary form of a browser observation."""
    if message.id.startswith(_OBSERVATION):
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
