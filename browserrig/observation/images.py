from dataclasses import dataclass, field, replace

from harnessed import Inject, Plugin, PluginState, SystemSection, hook
from harnessed.hooks import Next, PrepareRequest
from harnessed.models import ImagePart, ModelRequest, TextPart, User

from browserrig.events import ObservationCapturedEvent

from .models import CapturedImage
from .plugin import Observe


@dataclass
class _State:
    images: list[CapturedImage] = field(default_factory=list)


class ImageContext(Plugin, needs=(Observe,)):
    """Keep the latest N actual captures, independently of text observation history."""

    _state = PluginState(_State)
    _observe: Inject[Observe]

    usage = SystemSection(
        title="Browser image history",
        text=(
            "Images are labelled with capture time, tab and document. Historical images are "
            "for comparison only. Coordinate tools use the newest shown image for the current "
            "document, including its crop and zoom, even after text-only observations. "
            "Request a fresh screenshot when the visible layout changes."
        ),
    )

    def __init__(self, keep_latest_n_screenshots: int = 1) -> None:
        super().__init__()
        if (
            not isinstance(keep_latest_n_screenshots, int)
            or isinstance(keep_latest_n_screenshots, bool)
            or keep_latest_n_screenshots < 1
        ):
            raise ValueError("keep_latest_n_screenshots must be a positive integer")
        self.keep_latest_n_screenshots = keep_latest_n_screenshots

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
        images.append(CapturedImage.from_snapshot(snapshot, event.browser_id))
        del images[: -self.keep_latest_n_screenshots]

    @hook(PrepareRequest)
    async def _prepare(self, _event: PrepareRequest, next_: Next[ModelRequest]) -> ModelRequest:
        request = await next_()
        images = self._state.images
        if not images:
            return request
        snapshot = self._observe.snapshot
        messages = []
        for image in images:
            current = (
                image is images[-1]
                and snapshot is not None
                and (image.tab_id, image.document_id) == (snapshot.tab_id, snapshot.document_id)
            )
            label = "Latest coordinate image" if current else "Historical image; comparison only"
            caption = (
                f"{label}: {image.id}; captured={image.captured_at.isoformat()}; "
                f"browser={image.browser_id}; tab={image.tab_id}; document={image.document_id}"
            )
            if image.geometry is not None:
                caption += f"; geometry={image.geometry.model_dump_json()}"
            messages.append(
                User(
                    (TextPart(caption), ImagePart(f"data:image/png;base64,{image.image}")),
                    id=f"browser-image:{image.id}",
                )
            )
        self._observe.image_delivered(images[-1])
        return replace(request, messages=(*request.messages, *messages))
