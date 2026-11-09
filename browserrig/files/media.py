import mutagen

from .content import ParsedContent, ReadContext


def read_media(context: ReadContext) -> ParsedContent:
    media = mutagen.File(context.path)
    blocks = [
        f"# Media file\n\nName: {context.path.name}\nSize: {context.path.stat().st_size} bytes\n\n"
    ]
    if media is not None:
        for name in ("length", "bitrate", "sample_rate", "channels"):
            value = getattr(media.info, name, None)
            if isinstance(value, (int, float, str)):
                blocks.append(f"{name}: {value}\n")
    return ParsedContent(
        blocks,
        context.path.suffix.lstrip("."),
        [
            "Metadata only; audio transcription and video understanding are not available"
        ],
        status="metadata_only",
    )
