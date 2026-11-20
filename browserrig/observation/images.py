import asyncio
import base64
import hashlib
from dataclasses import replace
from itertools import chain

from harnessed.events import ObservationsIncludedEvent
from harnessed.models import (
    ImagePart,
    ImageReference,
    ModelRequest,
    TextPart,
    UserMessage,
)
from harnessed.sessions.log import SessionLog

from browserrig.core import Bounds

from .config import ScreenshotPolicy
from .drawing import ImageAnnotator, annotate
from .models import CapturedImage, Snapshot
from .state import ImageState
from .telemetry import trace_image

NOTE_SOURCE = "browser-image"


async def project_image(
    snapshot: Snapshot,
    browser_id: str,
    state: ImageState,
    *,
    options: ScreenshotPolicy,
    annotators: tuple[ImageAnnotator, ...] = (),
) -> CapturedImage | None:
    if snapshot.image is None:
        return None
    image = CapturedImage.from_snapshot(snapshot, browser_id)
    if annotators:
        pixels = await asyncio.to_thread(
            annotate,
            image.image,
            snapshot,
            annotators,
            _image_area(image),
            scale=image.geometry.scale if image.geometry is not None else 1.0,
        )
        image = replace(image, image=pixels)
    retained = state.images
    if options.skip_unchanged and retained and _same_screen(retained[-1], image):
        state.projected_id = image.id
        trace_image(image, "skipped_unchanged", reused_id=retained[-1].id)
        return None
    asset_id = await asyncio.to_thread(_asset_id, image.image)
    image = replace(image, asset_id=asset_id)
    retained.append(image)
    overflow = options.retention.overflow(len(retained))
    if overflow:
        for dropped in retained[:overflow]:
            trace_image(dropped, "dropped_by_retention")
        del retained[:overflow]
    if retained:
        state.pending = image
    state.projected_id = image.id
    return image


def attach_image(message: UserMessage | None, image: CapturedImage) -> UserMessage:
    parts = (
        TextPart(_caption(image)),
        ImagePart(f"data:image/png;base64,{image.image}"),
    )
    if message is None:
        return UserMessage(content=parts)
    if isinstance(message.content, str):
        return replace(message, content=(TextPart(message.text), *parts))
    return replace(message, content=(*message.content, *parts))


def image_note(state: ImageState, snapshot: Snapshot) -> str:
    if not state.images:
        return ""
    latest = state.images[-1]
    text = f"Latest captured screenshot: {latest.id}"
    if (latest.tab_id, latest.document_id) != (snapshot.tab_id, snapshot.document_id):
        return text + " (another document)"
    if snapshot.image is not None and snapshot.id != latest.id:
        return text + " (screen unchanged this step)"
    return text


def trim_images(
    request: ModelRequest, log: SessionLog, state: ImageState
) -> ModelRequest:
    retained = {image.id for image in state.images}
    included = log.included_observations(request)
    dropped = {
        item.message_id
        for item in included
        if item.source == "browser" and not retained.intersection(item.refs)
    }
    shown = retained.intersection(
        chain.from_iterable(item.refs for item in included if item.source == "browser")
    )
    stale = {
        item.message_id
        for item in included
        if item.source == NOTE_SOURCE and not shown.intersection(item.refs)
    }
    messages = []
    for message in request.messages:
        if message.id in stale:
            continue
        if message.id in dropped and not isinstance(message.content, str):
            content = tuple(
                part
                for part in message.content
                if not isinstance(part, ImagePart | ImageReference)
            )
            if (
                content
                and len(content) != len(message.content)
                and isinstance(content[-1], TextPart)
                and content[-1].text.startswith("Screenshot ")
            ):
                content = content[:-1]
            if not content:
                continue
            message = replace(message, content=content)
        messages.append(message)
    return replace(request, messages=tuple(messages))


def include_images(
    event: ObservationsIncludedEvent, log: SessionLog, state: ImageState
) -> CapturedImage | None:
    """Confirm assets in the final request, including after compaction and request hooks."""
    if not state.images:
        return None
    recorded = log.request(event.request_id)
    message_ids = {
        item.message_id for item in event.observations if item.source == "browser"
    }
    assets_by_message = (
        {
            message.id: {
                part.asset.sha256
                for part in message.content
                if isinstance(part, ImageReference)
            }
            for message in recorded.messages
            if message.id in message_ids and not isinstance(message.content, str)
        }
        if recorded is not None
        else {}
    )
    assets_by_ref = {}
    for item in event.observations:
        assets = assets_by_message.get(item.message_id)
        if item.source == "browser" and assets:
            assets_by_ref.update(dict.fromkeys(item.refs, assets))
    images = state.images
    images[:] = [
        image for image in images if image.asset_id in assets_by_ref.get(image.id, ())
    ]
    pending, state.pending = state.pending, None
    if pending is not None:
        outcome = "delivered" if pending in images else "not_included"
        trace_image(pending, outcome, request_id=event.request_id)
    return images[-1] if images else None


def discard_pending_image(state: ImageState) -> None:
    pending, state.pending = state.pending, None
    if pending is not None:
        state.images[:] = [image for image in state.images if image.id != pending.id]
        trace_image(pending, "not_included")


def _asset_id(image: str) -> str:
    return hashlib.sha256(base64.b64decode(image)).hexdigest()


def _image_area(image: CapturedImage) -> Bounds:
    geometry = image.geometry
    if geometry is not None:
        return Bounds(
            x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height
        )
    return Bounds(x=0, y=0, width=image.width, height=image.height)


def _same_screen(kept: CapturedImage, new: CapturedImage) -> bool:
    return (
        kept.tab_id,
        kept.document_id,
        kept.viewport_revision,
        kept.generation,
        kept.width,
        kept.height,
        kept.geometry,
        kept.image,
    ) == (
        new.tab_id,
        new.document_id,
        new.viewport_revision,
        new.generation,
        new.width,
        new.height,
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
