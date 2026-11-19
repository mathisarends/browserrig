import asyncio
from dataclasses import replace
from itertools import chain

from harnessed import SessionLog
from harnessed.models import (
    ImagePart,
    ImageReference,
    ModelRequest,
    TextPart,
    UserMessage,
)

from browserrig.core import Bounds

from .config import Screenshots
from .marks import annotate
from .models import CapturedImage, Snapshot
from .state import ImageState

NOTE_SOURCE = "browser-image"


async def project_image(
    snapshot: Snapshot, browser_id: str, state: ImageState, *, options: Screenshots
) -> CapturedImage | None:
    if snapshot.image is None:
        return None
    image = CapturedImage.from_snapshot(snapshot, browser_id)
    cursor = snapshot.cursor if options.cursor else None
    if options.marks is not None or cursor is not None:
        area = _image_area(image)
        pixels = await asyncio.to_thread(
            annotate,
            image.image,
            snapshot.elements if options.marks is not None else (),
            area,
            scale=image.geometry.scale if image.geometry is not None else 1.0,
            cursor=cursor,
        )
        image = replace(image, image=pixels)
    retained = state.images
    if options.skip_unchanged and retained and _same_screen(retained[-1], image):
        return None
    retained.append(image)
    overflow = options.retention.overflow(len(retained))
    if overflow:
        del retained[:overflow]
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
