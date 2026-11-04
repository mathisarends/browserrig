from dataclasses import dataclass, replace
from typing import Protocol

from harnessed import Instructions, Observation, Plugin, PluginState, SystemPrompt, hook
from harnessed.events import ObservationsIncludedEvent
from harnessed.hooks import Next, PrepareRequest, PreStep, StepDecision
from harnessed.kernel import dependency
from harnessed.models import ImagePart, ImageReference, ModelRequest, TextPart

from browserrig.events import ObservationCapturedEvent

from .models import CapturedImage
from .plugin import BrowserPerception
from .state import ImageState

_INSTRUCTIONS = Instructions(
    title="Browser image history",
    text=(
        "Screenshots belong to the browser observations they were captured with and are "
        "labelled with capture time, tab and document. A note names the latest captured "
        "screenshot whenever that changes. Coordinate tools use the latest screenshot "
        "included in the request, including its crop and zoom, while it shows the current "
        "document. Without an included screenshot they use viewport CSS pixels."
    ),
)


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
            min_images = (
                max(1, max_images // 2) if _positive(max_images) else max_images
            )
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


_NOTE_SOURCE = "browser-image"


class ImageContext(Plugin, slot="browserrig.images"):
    """Deliver screenshots inside immutable, session-owned browser observations.

    Retention can remove old image parts while keeping their DOM text. Native
    compaction removes text and images together in the request applying its summary.
    Coordinate geometry follows final inclusion receipts, after all request hooks.
    """

    _state = PluginState(ImageState)
    _observe = dependency(BrowserPerception)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    def __init__(
        self, retention: ImageRetention | None = None, *, skip_unchanged: bool = True
    ) -> None:
        super().__init__()
        self.retention = retention if retention is not None else TrimInBatches()
        self.skip_unchanged = skip_unchanged

    @property
    def images(self) -> tuple[CapturedImage, ...]:
        return tuple(self._state.images)

    @hook(ObservationCapturedEvent)
    async def _captured(self, event: ObservationCapturedEvent) -> None:
        snapshot = self._observe.snapshot
        if (
            snapshot is None
            or snapshot.id != event.observation_id
            or snapshot.image is None
        ):
            return
        images = self._state.images
        if any(image.id == snapshot.id for image in images):
            return
        image = CapturedImage.from_snapshot(snapshot, event.browser_id)
        if self.skip_unchanged and images and _same_screen(images[-1], image):
            return
        images.append(image)
        overflow = self.retention.overflow(len(images))
        if overflow:
            del images[:overflow]

    @hook(PreStep)
    async def _before_step(
        self, event: PreStep, next_: Next[StepDecision]
    ) -> StepDecision:
        # Wrap capture regardless of plugin order; session.observe replaces its pending source.
        decision = await next_()
        snapshot = self._observe.snapshot
        image = next(
            (
                image
                for image in self._state.images
                if snapshot is not None and image.id == snapshot.id
            ),
            None,
        )
        if image is not None and snapshot is not None:
            observation = self._observe.project(snapshot)
            event.session.observe(
                replace(
                    observation,
                    content=(
                        TextPart(str(observation.content)),
                        TextPart(_caption(image)),
                        ImagePart(f"data:image/png;base64,{image.image}"),
                    ),
                )
            )
        self._note(event)
        return decision

    @hook(PrepareRequest)
    async def _prepare(
        self, event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        retained = {image.id for image in self._state.images}
        included = event.session.log.included_observations(request)
        dropped = {
            item.message_id
            for item in included
            if item.source == "browser" and not retained.intersection(item.refs)
        }
        shown = retained.intersection(
            ref for item in included if item.source == "browser" for ref in item.refs
        )
        # A note about a screenshot leaves the context together with that screenshot.
        stale = {
            item.message_id
            for item in included
            if item.source == _NOTE_SOURCE and not shown.intersection(item.refs)
        }
        messages = tuple(
            replace(
                message,
                content=tuple(
                    part
                    for part in message.content
                    if not isinstance(part, ImagePart | ImageReference)
                ),
            )
            if message.id in dropped and not isinstance(message.content, str)
            else message
            for message in request.messages
            if message.id not in stale
        )
        return replace(request, messages=messages)

    @hook(ObservationsIncludedEvent)
    async def _included(self, event: ObservationsIncludedEvent) -> None:
        # Receipts reflect compaction and transformations after PrepareRequest as well.
        refs = {
            ref
            for item in event.observations
            if item.source == "browser"
            for ref in item.refs
        }
        self._state.images[:] = [
            image for image in self._state.images if image.id in refs
        ]
        self._observe.image_delivered(
            self._state.images[-1] if self._state.images else None
        )

    def _note(self, event: PreStep) -> None:
        # Recorded once per change, so earlier requests stay a prefix of later ones.
        images = self._state.images
        text = self._latest_note(images[-1]) if images else ""
        if text and text != self._state.note:
            event.session.observe(
                Observation(source=_NOTE_SOURCE, content=text, refs=(images[-1].id,))
            )
        self._state.note = text

    def _latest_note(self, latest: CapturedImage) -> str:
        snapshot = self._observe.snapshot
        text = f"Latest captured screenshot: {latest.id}"
        if snapshot is None or (latest.tab_id, latest.document_id) != (
            snapshot.tab_id,
            snapshot.document_id,
        ):
            text += " (another document)"
        elif snapshot.image is not None and snapshot.id != latest.id:
            text += " (screen unchanged this step)"
        return text


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _same_screen(kept: CapturedImage, new: CapturedImage) -> bool:
    return (kept.tab_id, kept.document_id, kept.geometry, kept.image) == (
        new.tab_id,
        new.document_id,
        new.geometry,
        new.image,
    )


def _caption(image: CapturedImage) -> str:
    caption = (
        f"Screenshot {image.id}; captured={image.captured_at.isoformat()}; "
        f"browser={image.browser_id}; tab={image.tab_id}; document={image.document_id}"
    )
    if image.geometry is not None:
        caption += f"; geometry={image.geometry.model_dump_json()}"
    return caption
