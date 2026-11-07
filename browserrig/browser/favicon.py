import asyncio
import base64
import re
from contextlib import suppress
from urllib.parse import unquote_to_bytes, urlsplit

from cdpify import CDPError, CdpSession
from cdpify.domains.network import LoadNetworkResourceOptions

# Icons travel inside live events, so oversized ones are dropped instead of streamed.
_MAX_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 5
_CLOSE_SECONDS = 1
_CHUNK_BYTES = 16 * 1024

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"BM", "image/bmp"),
)
_SVG_PREAMBLE = re.compile(rb"^(?:\s|<\?xml[^>]*\?>|<!--.*?-->)*", re.S)


async def load_favicon(cdp: CdpSession, frame_id: str, url: str) -> str:
    """Return the page's icon as a base64 `data:` URI, or "" when it is missing or unusable.

    Web icons load through the page's own network stack without cookies, so icons behind
    a login do not load. Inline `data:` icons are decoded locally. Either way the type
    comes from the bytes. SVG stays safe only while viewers render it with `<img>`, never
    through `innerHTML` or `<object>`.
    """
    scheme = urlsplit(url).scheme
    try:
        if scheme == "data":
            data = _decode_data_uri(url)
        elif scheme in {"http", "https"}:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                data = await _fetch(cdp, frame_id, url)
        else:
            return ""
    except (CDPError, TimeoutError, ValueError):
        return ""
    if not data or (media_type := _media_type(data)) is None:
        return ""
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def _decode_data_uri(url: str) -> bytes | None:
    header, separator, payload = url.removeprefix("data:").partition(",")
    if not separator:
        return None
    if header.lower().endswith(";base64"):
        encoded = b"".join(unquote_to_bytes(payload).split())
        data = base64.b64decode(encoded, validate=True)
    else:
        data = unquote_to_bytes(payload)
    return data if len(data) <= _MAX_BYTES else None


async def _fetch(cdp: CdpSession, frame_id: str, url: str) -> bytes | None:
    result = await cdp.network.load_network_resource(
        frame_id=frame_id,
        url=url,
        options=LoadNetworkResourceOptions(
            disable_cache=False, include_credentials=False
        ),
    )
    resource = result.resource
    if not resource.success or resource.stream is None:
        return None
    try:
        status = resource.http_status_code
        if status is not None and not 200 <= status < 300:
            return None
        return await _read(cdp, resource.stream)
    finally:
        # Closing must neither hang after a timeout nor replace the result with its error.
        with suppress(CDPError, TimeoutError):
            async with asyncio.timeout(_CLOSE_SECONDS):
                await cdp.io.close(handle=resource.stream)


async def _read(cdp: CdpSession, handle: str) -> bytes | None:
    data = bytearray()
    while len(data) <= _MAX_BYTES:
        chunk = await cdp.io.read(handle=handle, size=_CHUNK_BYTES)
        data += (
            base64.b64decode(chunk.data, validate=True)
            if chunk.base64_encoded
            else chunk.data.encode()
        )
        if chunk.eof:
            return bytes(data) if len(data) <= _MAX_BYTES else None
    return None


def _media_type(data: bytes) -> str | None:
    # The page controls both the icon URL and its headers, so only the bytes decide.
    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    head = data[:2048].lstrip(b"\xef\xbb\xbf").lower()
    # An XHTML page may start with an XML prolog and embed inline SVG.
    if b"<html" in head:
        return None
    body = _SVG_PREAMBLE.sub(b"", head)
    if body.startswith(b"<svg") or (
        body.startswith(b"<!doctype svg") and b"<svg" in body
    ):
        return "image/svg+xml"
    return None
